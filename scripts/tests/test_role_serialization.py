"""Pure serializer regression checks; database integration cases live under backend/tests."""
import ast
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch


class RoleSerializationTests(unittest.TestCase):
    def render(self, users, direct=(), inherited=()):
        path = Path(__file__).resolve().parents[2] / 'backend/app/users/routes.py'
        node = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == '_list_details')
        namespace = {'Session': object, 'user_group_association': SimpleNamespace(c=SimpleNamespace(user_id=MagicMock(), group_id=MagicMock()))}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
        models = ModuleType('backend.app.admin_roles.models')
        models.AdminRoleAssignment = SimpleNamespace(user_id=MagicMock(), role=MagicMock())
        models.GroupAdminRole = SimpleNamespace(group_id=MagicMock(), role=MagicMock())
        permissions = ModuleType('backend.app.admin_roles.permissions')
        permissions.ROLES = {'org_admin': {'label': 'Organization administrator'}, 'app_admin': {'label': 'Application administrator'}}
        query1, query2 = MagicMock(), MagicMock()
        query1.filter.return_value = direct
        query2.join.return_value.filter.return_value = inherited
        db = MagicMock()
        db.query.side_effect = [query1, query2]
        with patch.dict(sys.modules, {'backend.app.admin_roles.models': models, 'backend.app.admin_roles.permissions': permissions}):
            result = namespace['_list_details'](db, users)
        return result, db

    def user(self, uid):
        return SimpleNamespace(id=uid, to_dict=lambda: {'id': uid})

    def test_batch_deduplicates_direct_and_group_roles(self):
        rows, db = self.render([self.user(1), self.user(2)], [(1, 'org_admin')], [(1, 'org_admin'), (1, 'app_admin')])
        self.assertEqual(db.query.call_count, 2)
        self.assertEqual(rows[0]['admin_roles'], [
            {'id': 'app_admin', 'label': 'Application administrator', 'sources': ['group']},
            {'id': 'org_admin', 'label': 'Organization administrator', 'sources': ['direct', 'group']},
        ])
        self.assertEqual(rows[1]['admin_roles'], [])

    def test_empty_page_does_not_query_roles(self):
        rows, db = self.render([])
        self.assertEqual(rows, [])
        db.query.assert_not_called()
