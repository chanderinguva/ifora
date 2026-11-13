// Run from frontend: node --test tests/portal-guides.test.cjs
// Exercises real TS/TSX modules through the project's installed TypeScript/React.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const src = path.resolve(__dirname, '../src');
function loader(overrides = {}) {
  const cache = new Map();
  function load(name, parent = src) {
    if (name in overrides) return overrides[name];
    if (!name.startsWith('@/') && !name.startsWith('.') && !path.isAbsolute(name)) return require(name);
    let file = name.startsWith('@/') ? path.join(src, name.slice(2)) : path.resolve(parent, name);
    file = [file, file + '.ts', file + '.tsx'].find(p => fs.existsSync(p) && fs.statSync(p).isFile());
    if (!file) throw Error('Missing module: ' + name);
    if (cache.has(file)) return cache.get(file).exports;
    const module = {exports: {}}; cache.set(file, module);
    const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true, target: ts.ScriptTarget.ES2022 } }).outputText;
    vm.runInNewContext(code, { module, exports: module.exports, require: n => load(n, path.dirname(file)), console, URL, process, setTimeout, clearTimeout }, {filename: file});
    return module.exports;
  }
  return load;
}
const load = loader();
const { isPersonalRoute } = load('@/lib/personal-navigation');
test('personal navigation stays separate from administrative routes', () => {
  for (const route of ['/dashboard', '/apps', '/apps/request', '/settings']) assert.equal(isPersonalRoute(route), true);
  for (const route of ['/admin/dashboard', '/admin/applications/1', '/apps-evil', '/login']) assert.equal(isPersonalRoute(route), false);
});
for (const personal of [false, true]) for (const collapsed of [false, true]) {
  test(`shortcut opens a separate safe tab: personal=${personal}, collapsed=${collapsed}`, () => {
    const { DashboardShortcut } = load('@/components/dashboard-shortcut');
    const html = renderToStaticMarkup(React.createElement(DashboardShortcut, {personal, collapsed}));
    assert.ok(html.includes(`href="${personal ? '/admin/dashboard' : '/dashboard'}"`));
    assert.ok(html.includes('target="_blank"'));
    assert.ok(html.includes('rel="noopener noreferrer"'));
    assert.ok(html.includes('opens in a new tab'));
  });
}
test('guide suggestion validates vendor hostname instead of name substrings', () => {
  const { suggestedSamlGuide } = load('@/lib/saml-guides');
  assert.equal(suggestedSamlGuide('', 'https://inguva.slack.com/sso/saml'), 'slack');
  assert.equal(suggestedSamlGuide('https://slack.com', ''), 'slack');
  assert.equal(suggestedSamlGuide('', 'https://inguva.slack.com.evil.example/sso/saml'), 'generic');
  assert.equal(suggestedSamlGuide('', 'not a URL'), 'generic');
});
const idp = { entity_id: 'https://ifora.example/idp', sso_url: 'https://ifora.example/sso', metadata_url: 'https://ifora.example/metadata' };
const provider = { sp_entity_id: 'https://slack.com', acs_url: 'https://team.slack.com/sso/saml', audience: null, name_id_format: 'persistent', signing: 'both', attribute_mappings: [{name:'User.Email', source:'email', required:true}], idp: {...idp, certificate_pem: 'PUBLIC-CERT-TEST'} };
test('setup guide renders saved values, source links and required Slack claim checks', () => {
  const { SamlSetupGuide } = load('@/components/saml-setup-guide');
  const html = renderToStaticMarkup(React.createElement(SamlSetupGuide, {idp, provider, dirty:false}));
  for (const value of [idp.sso_url, idp.entity_id, provider.acs_url, 'PUBLIC-CERT-TEST', 'Configured', 'https://slack.com/help/articles/205168057']) assert.ok(html.includes(value));
});
test('unsaved and unconfigured guides block copying rather than presenting draft values as live', () => {
  const { SamlSetupGuide } = load('@/components/saml-setup-guide');
  const dirty = renderToStaticMarkup(React.createElement(SamlSetupGuide, {idp, provider, dirty:true}));
  assert.ok(dirty.includes('You have unsaved changes'));
  assert.equal((dirty.match(/disabled=""/g) || []).length, 6);
  const empty = renderToStaticMarkup(React.createElement(SamlSetupGuide, {idp, provider:null, dirty:false}));
  assert.ok(empty.includes('Save your SAML configuration first'));
  assert.ok(!empty.includes('PUBLIC-CERT-TEST'));
});
test('saved values are escaped as text, never rendered as executable HTML', () => {
  const { SamlSetupGuide } = load('@/components/saml-setup-guide');
  const html = renderToStaticMarkup(React.createElement(SamlSetupGuide, {idp:{...idp, entity_id:'<script>bad()</script>'}, provider, dirty:false}));
  assert.ok(!html.includes('<script>bad()'));
  assert.ok(html.includes('&lt;script&gt;'));
});
test('SCIM setup attaches to the existing app, leaves group push and provisioning off', () => {
  const { scimSetupBody } = load('@/lib/provisioning');
  const body = scimSetupBody(42, 'Slack', {url:'https://api.slack.com/scim/v2', auth:'bearer', secret:'test-only', header:'', tokenUrl:'', clientId:'', scope:'', updates:'patch'});
  assert.equal(body.application_id, 42); assert.equal(body.name, 'Slack');
  assert.equal(body.enabled, false); assert.equal(body.options.push_groups, false);
  assert.equal(body.kind, 'scim'); assert.equal(body.header_name, null);
  assert.equal(body.options.update_style, 'patch');
});
test('SCIM custom-header and OAuth settings preserve authentication fields', () => {
  const { scimSetupBody } = load('@/lib/provisioning');
  const connection = {url:'https://service.example/scim', auth:'oauth2', secret:'test-only', header:'X-Test', tokenUrl:'https://service.example/token', clientId:'test-client', scope:'users.write', updates:'put'};
  assert.equal(scimSetupBody(1,'Test',connection).token_url, connection.tokenUrl);
  assert.equal(scimSetupBody(1,'Test',{...connection, auth:'header'}).header_name, 'X-Test');
});
for (const pathname of ['/admin/dashboard', '/dashboard', '/apps']) {
  test(`role shell chooses presentation per route without changing admin role: ${pathname}`, () => {
    const user = {is_admin:true, acting_as_user:false};
    const roleLoad = loader({
      'next/navigation': {usePathname:()=>pathname},
      './auth-guard': {useCurrentUser:()=>user},
      './app-shell': {AppShell: ({title, children})=>React.createElement('div',{'data-title':title}, children)},
      './command-palette': {CommandPalette:()=>null},
    });
    const { RoleShell } = roleLoad('@/components/role-shell');
    const html = renderToStaticMarkup(React.createElement(RoleShell, null, 'Content'));
    assert.ok(html.includes(`data-title="${pathname.startsWith('/admin') ? 'Administration' : 'My account'}"`));
    assert.equal(user.acting_as_user, false);
  });
}

test('user role labels show assigned organization and group-derived roles', () => {
  const { UserRoleBadges } = load('@/components/user-role-badges');
  const html = renderToStaticMarkup(React.createElement(UserRoleBadges, {user: {is_admin:true, is_super_admin:false, admin_roles: [
    {id:'org_admin',label:'Organization administrator',sources:['direct']},
    {id:'app_admin',label:'Application administrator',sources:['group']},
  ]}}));
  assert.ok(html.includes('Organization administrator'));
  assert.ok(html.includes('Application administrator'));
  assert.ok(html.includes('Granted through a group'));
  assert.ok(!html.includes('>Admin<'));
});
test('roleless admin is not mislabeled as organization admin', () => {
  const { UserRoleBadges } = load('@/components/user-role-badges');
  const html = renderToStaticMarkup(React.createElement(UserRoleBadges, {user:{is_admin:true,is_super_admin:false,admin_roles:[]}}));
  assert.ok(html.includes('Admin (no role assigned)'));
  assert.ok(!html.includes('Organization administrator'));
});

test('translator handles user and filtered group claims without making requests', () => {
  const { translateSamlConfig } = load('@/lib/saml-config-translator');
  const plan = translateSamlConfig('Use persistent Name ID\nSign both\nSend email as User.Email required\nSend groups starting with app- as groups');
  assert.equal(plan.errors.length, 0); assert.equal(plan.fields.name_id_format, 'persistent'); assert.equal(plan.fields.signing, 'both');
  assert.equal(plan.claims[0].name, 'User.Email'); assert.equal(plan.claims[0].required, true);
  assert.equal(plan.claims[1].source, 'groups'); assert.equal(plan.claims[1].filter.type, 'starts_with');
  assert.equal(plan.claims[1].filter.value, 'app-');
});
test('translator rejects unsupported, conflicting and secret-bearing URL instructions', () => {
  const { translateSamlConfig } = load('@/lib/saml-config-translator');
  for (const request of ['Make everyone an org admin', 'Enable provisioning', 'Use email Name ID\nUse persistent Name ID', 'Set ACS URL to https://user:password@example.com/acs', 'Set ACS URL to http://example.com/acs', 'Set ACS URL to https://example.com/acs#secret']) assert.ok(translateSamlConfig(request).errors.length);
});
test('translator updates only named claims while preserving other mappings', () => {
  const { mergeClaims, translateSamlConfig } = load('@/lib/saml-config-translator');
  const old = [{name:'email',source:'email'}, {name:'groups',source:'groups',filter:{type:'equals',value:'old'}}];
  const plan = translateSamlConfig('Send groups containing engineering as groups');
  const merged = mergeClaims(old, plan.claims);
  assert.equal(merged.length, 2); assert.equal(merged[0].name, 'email');
  assert.equal(merged[1].filter.value, 'engineering'); assert.equal(old[1].filter.value, 'old');
});

test('group push panel uses shared assignments and keeps writes unavailable to read-only admins', () => {
  const { PushGroupsPanel } = load('@/components/push-groups-panel');
  const html = renderToStaticMarkup(React.createElement(PushGroupsPanel, {
    app: {id:1, options:{push_groups:false}}, canEdit:false,
    assignments:[{id:1,type:'group',subject_id:2,name:'Engineering'},{id:2,type:'user',subject_id:3,name:'Hidden user'}],
    links:[{id:1,type:'group',label:'Engineering',state:'synced'}], onUpdated:()=>{},
  }));
  assert.ok(html.includes('Engineering')); assert.ok(html.includes('synced'));
  assert.ok(!html.includes('Hidden user'));
  assert.ok(!html.includes('Save group-push settings'));
  assert.ok(html.includes('disabled=""'));
});
