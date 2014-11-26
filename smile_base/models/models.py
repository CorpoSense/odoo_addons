# -*- encoding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2013 Smile (<http://www.smile.fr>). All Rights Reserved
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

import logging

from openerp import api
from openerp.osv import fields
from openerp.models import BaseModel

_logger = logging.getLogger(__name__)

native_auto_init = BaseModel._auto_init
native_validate_fields = BaseModel._validate_fields
native_import_data = BaseModel.import_data
native_load = BaseModel.load
native_unlink = BaseModel.unlink


def new_auto_init(self, cr, context=None):
    '''Add foreign key with ondelete = 'set null' for stored fields.function of type many2one'''
    res = native_auto_init(self, cr, context)
    for fieldname, field in self._columns.iteritems():
        if isinstance(field, fields.function) and field._type == 'many2one' and field.store:
            self._m2o_fix_foreign_key(cr, self._table, fieldname, self.pool.get(field._obj), 'set null')
    return res


@api.multi
def new_validate_fields(self, fields_to_validate):
    context = self._context
    if not context.get('no_validate'):
        native_validate_fields(self, fields_to_validate)


# Helper function combining _store_get_values and _store_set_values
@api.multi
def _compute_store_set(self):
    """
    Get the list of stored function field to recompute (via _store_get_values)
    and recompute them (via _store_set_values)
    """
    cr, uid, context = self.env.args
    store_get_result = self._store_get_values(self._columns.keys())
    store_get_result.sort()
    done = {}
    for order, model, ids_to_update, fields_to_recompute in store_get_result:
        key = (model, tuple(fields_to_recompute))
        done.setdefault(key, {})
        # avoid to do several times the same computation
        todo = []
        for id_to_update in ids_to_update:
            if id_to_update not in done[key]:
                done[key][id_to_update] = True
                todo.append(id_to_update)
        self.pool[model]._store_set_values(cr, uid, todo, fields_to_recompute, context)


def new_load(self, cr, uid, fields, data, context=None):
    context_copy = context and context.copy() or {}
    context_copy['no_store_function'] = True
    context_copy['no_validate'] = True
    context_copy['defer_parent_store_computation'] = True
    res = native_load(self, cr, uid, fields, data, context_copy)
    ids = res['ids']
    if ids:
        recs = self.browse(cr, uid, ids, context)
        recs._compute_store_set()
        recs._validate_fields(fields)
        self._parent_store_compute(cr)
    return res


def new_import_data(self, cr, uid, fields, datas, mode='init', current_module='', noupdate=False, context=None, filename=None):
    context_copy = context and context.copy() or {}
    context_copy['defer_parent_store_computation'] = True
    return native_import_data(self, cr, uid, fields, datas, mode, current_module, noupdate, context_copy, filename)


@api.multi
def new_unlink(self):
    if hasattr(self.pool[self._name], '_cascade_relations'):
        self = self.with_context(active_test=False)
        if 'unlink_in_cascade' not in self._context:
            self = self.with_context(unlink_in_cascade={self._name: list(self._ids)})
        for model, fnames in self.pool[self._name]._cascade_relations.iteritems():
            domain = ['|'] * (len(fnames) - 1) + [(fname, 'in', self._ids) for fname in fnames]
            sub_model_obj = self.env[model]
            sub_models = sub_model_obj.search(domain)
            sub_model_ids = list(set(sub_models._ids) - set(self._context['unlink_in_cascade'].get(model, [])))
            if sub_model_ids:
                self._context['unlink_in_cascade'].setdefault(model, []).extend(sub_model_ids)
                sub_model_obj.browse(sub_model_ids).unlink()
    if not self.exists():
        return True
    return native_unlink(self)


@api.model
@api.returns('self')
def bulk_create(self, vals_list):
    if not vals_list:
        return []
    cr, uid, context = self.env.args
    context_copy = context and context.copy() or {}
    context_copy['no_store_function'] = True
    context_copy['no_validate'] = True
    context_copy['defer_parent_store_computation'] = True
    ids = []
    if not isinstance(vals_list, list):
        vals_list = [vals_list]
    for vals in vals_list:
        ids.append(self.with_context(context_copy).create(vals).id)
    records = self.browse(ids)
    records._compute_store_set()
    records._validate_fields(vals_list[0])
    self._parent_store_compute()
    return records

BaseModel._auto_init = new_auto_init
BaseModel._compute_store_set = _compute_store_set
BaseModel._validate_fields = new_validate_fields
BaseModel.bulk_create = bulk_create
BaseModel.import_data = new_import_data
BaseModel.load = new_load
BaseModel.store_set_values = BaseModel._store_set_values
BaseModel.unlink = new_unlink
