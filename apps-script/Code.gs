/**
 * SalesOps Ticket Tracker — Google Apps Script web app.
 *
 * Emails sent to the salesops@bayut.sa GROUP become tickets. Deployed as a web
 * app that runs AS the deploying owner (a group member, so GmailApp sees the
 * group's mail) and is accessible to the bayut.sa DOMAIN (Google handles login).
 * The signed-in user (Session.getActiveUser) is checked against an access list
 * with role View (read-only) or Edit (can tag). Non-members request access; an
 * email goes to the admins who approve View/Edit from a link or the Admin page.
 *
 * Storage: a Google Sheet (auto-created) holds Access / Requests / Tags /
 * TicketIDs / Activity. The computed ticket list is cached (CacheService).
 */

// ------------------------------------------------------------------ CONFIG
var GROUP = 'salesops@bayut.sa';
var WINDOW_DAYS = 90;         // how far back to scan
var MAX_THREADS = 400;        // Gmail search cap per scan
var INBOUND_ONLY = true;      // exclude threads opened by a team member/system
var CACHE_TTL = 21600;        // 6h
var ADMINS = ['waheed.rasool@bayut.sa'];   // bootstrap admins (full access + manage)

var TAGS = ['Developer', 'SPA', 'RC', 'Refund', 'FYI'];
var RESPONDERS = {
  'salesops@bayut.sa': 'Sales Ops',
  'faisal.javed@bayut.sa': 'Faisal Javed',
  'aisha.naveed@bayut.sa': 'Aisha Naveed',
  'hazim.tahir@bayut.sa': 'Hazim Tahir',
  'aymansaber.alsabahy@bayut.sa': 'Ayman Saber',
  'fahad.dafer@bayut.sa': 'Fahad Dafer Alshehri',
  'waheed.tahir@bayut.sa': 'Waheed Tahir',
  'waheed.rasool@bayut.sa': 'Waheed Rasool',
  'mahmoud.elsayed@bayut.sa': 'Mahmoud Elsayed Elmshaikh',
  'abduljabbar.mohammed@bayut.sa': 'Abdul Jabbar Mohammed'
};

// ------------------------------------------------------------------ web entry
function doGet(e) {
  var user = activeEmail_();
  if (e && e.parameter && e.parameter.action === 'approve') {
    return approveByLink_(e.parameter, user);
  }
  return HtmlService.createTemplateFromFile('Index').evaluate()
    .setTitle('SalesOps Ticket Tracker')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function activeEmail_() {
  var e = Session.getActiveUser().getEmail() || Session.getEffectiveUser().getEmail() || '';
  return e.toLowerCase();
}
function webUrl_() { return ScriptApp.getService().getUrl(); }

// ------------------------------------------------------------------ roles
function roleOf_(email) {
  email = (email || '').toLowerCase();
  if (ADMINS.map(function (a) { return a.toLowerCase(); }).indexOf(email) >= 0) return 'admin';
  var a = readAccess_().users[email];
  return a ? a.role : null;
}
function canView_(e) { return ['admin', 'edit', 'view'].indexOf(roleOf_(e)) >= 0; }
function canEdit_(e) { return ['admin', 'edit'].indexOf(roleOf_(e)) >= 0; }
function isAdmin_(e) { return roleOf_(e) === 'admin'; }

// ------------------------------------------------------------------ client API
function getInit() {
  var me = meObj_();
  if (!me.canView) return { me: me, needAccess: true };
  return { me: me, data: getTicketsCached_() };
}
function meObj_() {
  var e = activeEmail_();
  return { email: e, role: roleOf_(e) || 'none', canView: canView_(e), canEdit: canEdit_(e), isAdmin: isAdmin_(e) };
}
function apiRefresh() {
  if (!canView_(activeEmail_())) throw new Error('Not authorized');
  return refreshTickets_();
}
function apiThread(threadId) {
  if (!canView_(activeEmail_())) throw new Error('Not authorized');
  return getThread_(threadId);
}
function apiSetTags(threadIds, addTag, clear) {
  var u = activeEmail_();
  if (!canEdit_(u)) throw new Error('You have view-only access.');
  setTags_(threadIds, addTag, clear, u);
  return refreshTickets_();
}
function apiActivity() {
  if (!canView_(activeEmail_())) throw new Error('Not authorized');
  return readActivity_(400);
}
function apiRequestAccess(note) {
  var email = activeEmail_();
  if (!email) throw new Error('Could not detect your Google identity.');
  addRequest_(email, note || '');
  var url = webUrl_();
  var vlink = url + '?action=approve&email=' + encodeURIComponent(email) + '&role=view';
  var elink = url + '?action=approve&email=' + encodeURIComponent(email) + '&role=edit';
  var body = '<b>' + esc_(email) + '</b> is requesting access to the SalesOps Ticket portal.'
    + (note ? '<br><br><i>Note:</i> ' + esc_(note) : '')
    + '<br><br>Grant access:<br><br>'
    + '<a href="' + vlink + '" style="background:#2563eb;color:#fff;padding:9px 16px;border-radius:8px;text-decoration:none;font-weight:700;margin-right:8px">Approve · View</a>'
    + '<a href="' + elink + '" style="background:#0d7a3f;color:#fff;padding:9px 16px;border-radius:8px;text-decoration:none;font-weight:700">Approve · Edit</a>'
    + '<br><br><span style="font-size:12px;color:#5d7168">Or manage access at <a href="' + url + '">the portal</a>.</span>';
  sendMail_(ADMINS.join(','), '[Access request] ' + email + ' — SalesOps portal', wrap_('Access request', body));
  return { ok: true };
}

// admin
function apiAdminList() {
  if (!isAdmin_(activeEmail_())) throw new Error('Admins only');
  return { users: listUsers_(), requests: listRequests_() };
}
function apiAdminSetRole(email, role) {
  if (!isAdmin_(activeEmail_())) throw new Error('Admins only');
  if (['view', 'edit'].indexOf(role) < 0 || !/@bayut\.sa$/i.test(email)) throw new Error('bad email/role');
  grant_(email.toLowerCase(), role, activeEmail_());
  notifyGranted_(email.toLowerCase(), role);
  return { ok: true };
}
function apiAdminRemove(email) {
  if (!isAdmin_(activeEmail_())) throw new Error('Admins only');
  revoke_(email.toLowerCase()); return { ok: true };
}
function apiAdminDeny(email) {
  if (!isAdmin_(activeEmail_())) throw new Error('Admins only');
  denyRequest_(email.toLowerCase()); return { ok: true };
}

function approveByLink_(p, user) {
  if (!isAdmin_(user)) {
    return HtmlService.createHtmlOutput('<p style="font-family:sans-serif">Not authorized to approve. Ask an admin.</p>');
  }
  var email = (p.email || '').toLowerCase(), role = p.role;
  if (['view', 'edit'].indexOf(role) < 0 || !/@bayut\.sa$/i.test(email)) {
    return HtmlService.createHtmlOutput('<p style="font-family:sans-serif">Invalid approval link.</p>');
  }
  grant_(email, role, user); notifyGranted_(email, role);
  return HtmlService.createHtmlOutput('<div style="font-family:Segoe UI,sans-serif;padding:24px">'
    + '<h2 style="color:#0d7a3f">Access granted</h2><b>' + esc_(email) + '</b> now has <b>' + role.toUpperCase()
    + '</b> access. <a href="' + webUrl_() + '">Open portal</a></div>');
}

// ------------------------------------------------------------------ Gmail scan
function refreshTickets_() {
  var payload = scanTickets_();
  putCache_(payload);
  return payload;
}
function getTicketsCached_() {
  var p = getCache_();
  return p || refreshTickets_();
}

function scanTickets_() {
  var q = '(to:' + GROUP + ' OR cc:' + GROUP + ') newer_than:' + WINDOW_DAYS + 'd';
  var threads = GmailApp.search(q, 0, MAX_THREADS);
  var mpt = GmailApp.getMessagesForThreads(threads);
  var tags = readTags_();
  var ids = readIds_();
  var maxNum = 0;
  Object.keys(ids).forEach(function (k) { var n = parseInt((ids[k] || '').split('-')[1] || '0', 10); if (n > maxNum) maxNum = n; });

  // order new threads by first-message date so older -> lower SO number
  var order = threads.map(function (th, i) { return { i: i, d: mpt[i].length ? mpt[i][0].getDate().getTime() : 0 }; })
    .sort(function (a, b) { return a.d - b.d; });
  var newIds = {};
  order.forEach(function (o) {
    var id = threads[o.i].getId();
    if (!ids[id]) { maxNum++; ids[id] = 'SO-' + ('00000' + maxNum).slice(-5); newIds[id] = ids[id]; }
  });
  if (Object.keys(newIds).length) appendIds_(newIds);

  var tickets = [], excluded = 0;
  for (var i = 0; i < threads.length; i++) {
    var th = threads[i], msgs = mpt[i];
    if (!msgs.length) continue;
    var opener = msgs[0], openerEmail = emailOf_(opener.getFrom());
    if (INBOUND_ONLY && RESPONDERS[openerEmail]) { excluded++; continue; }
    var openDt = opener.getDate();
    var respAt = null, responder = null;
    for (var j = 1; j < msgs.length; j++) {
      var fe = emailOf_(msgs[j].getFrom());
      if (RESPONDERS[fe]) { respAt = msgs[j].getDate(); responder = RESPONDERS[fe]; break; }
    }
    var id = th.getId();
    var tg = tags[id] || [];
    var subj = stripRe_(th.getFirstMessageSubject()) || '(no subject)';
    var t = {
      thrid: id, ticket_id: ids[id] || '', subject: subj,
      requester_name: nameOf_(opener.getFrom()), requester_addr: openerEmail,
      received: openDt.toISOString(), messages: msgs.length,
      tags: tg, fyi: tg.indexOf('FYI') >= 0
    };
    if (respAt) {
      t.status = 'responded'; t.responder = responder;
      t.responded_at = respAt.toISOString();
      t.response_secs = Math.round((respAt.getTime() - openDt.getTime()) / 1000);
    } else { t.status = 'open'; t.responder = null; t.response_secs = null; }
    tickets.push(t);
  }
  tickets.sort(function (a, b) { return a.received < b.received ? 1 : -1; });
  var openN = tickets.filter(function (t) { return t.status === 'open' && !t.fyi; }).length;
  var resp = tickets.filter(function (t) { return t.status === 'responded' && !t.fyi; });
  var avg = resp.length ? Math.round(resp.reduce(function (s, t) { return s + t.response_secs; }, 0) / resp.length) : 0;
  return {
    generated: new Date().toISOString(), group: GROUP, window_days: WINDOW_DAYS,
    excluded_internal: excluded, tag_list: TAGS, total: tickets.length,
    open: openN, responded: resp.length, fyi: tickets.filter(function (t) { return t.fyi; }).length,
    avg_response_secs: avg, tickets: tickets
  };
}

function getThread_(threadId) {
  var th = GmailApp.getThreadById(threadId);
  if (!th) return { error: 'not found' };
  var msgs = th.getMessages();
  var tags = readTags_()[threadId] || [];
  var timeline = msgs.map(function (m) {
    var body = (m.getPlainBody() || '').replace(/\s+\n/g, '\n').trim();
    return {
      from_name: nameOf_(m.getFrom()), from_addr: emailOf_(m.getFrom()),
      date: m.getDate().toISOString(), is_responder: !!RESPONDERS[emailOf_(m.getFrom())],
      summary: body.slice(0, 280) + (body.length > 280 ? '…' : '')
    };
  });
  var last = msgs[msgs.length - 1];
  return {
    ticket_id: readIds_()[threadId] || '', subject: stripRe_(th.getFirstMessageSubject()),
    requester: nameOf_(msgs[0].getFrom()), requester_addr: emailOf_(msgs[0].getFrom()),
    tags: tags, status: timeline.some(function (m, i) { return i > 0 && m.is_responder; }) ? 'responded' : 'open',
    timeline: timeline, latest_body: (last.getPlainBody() || '').slice(0, 4000), latest_from: nameOf_(last.getFrom())
  };
}

// ------------------------------------------------------------------ helpers (parse)
function emailOf_(from) { var m = (from || '').match(/<([^>]+)>/); return (m ? m[1] : from || '').trim().toLowerCase(); }
function nameOf_(from) { var m = (from || '').match(/^(.*?)</); return (m ? m[1] : from || '').replace(/"/g, '').trim(); }
function stripRe_(s) { return (s || '').replace(/^\s*(re|fwd|fw)\s*:\s*/i, '').trim(); }
function esc_(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

// ------------------------------------------------------------------ cache (chunked)
function putCache_(payload) {
  var c = CacheService.getScriptCache();
  var s = JSON.stringify(payload), size = 90000, n = Math.ceil(s.length / size), obj = {};
  for (var i = 0; i < n; i++) obj['tk_' + i] = s.substr(i * size, size);
  obj['tk_meta'] = JSON.stringify({ n: n, ts: payload.generated });
  c.putAll(obj, CACHE_TTL);
}
function getCache_() {
  var c = CacheService.getScriptCache();
  var meta = c.get('tk_meta'); if (!meta) return null;
  var n = JSON.parse(meta).n, keys = [];
  for (var i = 0; i < n; i++) keys.push('tk_' + i);
  var got = c.getAll(keys), s = '';
  for (var j = 0; j < n; j++) { if (!got['tk_' + j]) return null; s += got['tk_' + j]; }
  try { return JSON.parse(s); } catch (e) { return null; }
}

// ------------------------------------------------------------------ Sheet store
function book_() {
  var props = PropertiesService.getScriptProperties();
  var id = props.getProperty('SHEET_ID'), ss;
  if (id) { try { ss = SpreadsheetApp.openById(id); } catch (e) { ss = null; } }
  if (!ss) {
    ss = SpreadsheetApp.create('SalesOps Ticket Tracker — Data');
    props.setProperty('SHEET_ID', ss.getId());
  }
  ensureTab_(ss, 'Access', ['email', 'role', 'grantedBy', 'grantedAt']);
  ensureTab_(ss, 'Requests', ['email', 'requestedAt', 'note']);
  ensureTab_(ss, 'Tags', ['threadId', 'tags']);
  ensureTab_(ss, 'TicketIDs', ['threadId', 'ticketId']);
  ensureTab_(ss, 'Activity', ['ts', 'user', 'action', 'detail']);
  return ss;
}
function ensureTab_(ss, name, headers) {
  var sh = ss.getSheetByName(name);
  if (!sh) { sh = ss.insertSheet(name); sh.appendRow(headers); }
  return sh;
}
function tab_(name) { return book_().getSheetByName(name); }
function rows_(name) {
  var sh = tab_(name), v = sh.getDataRange().getValues();
  if (v.length < 2) return [];
  var head = v[0], out = [];
  for (var i = 1; i < v.length; i++) { var o = {}; for (var j = 0; j < head.length; j++) o[head[j]] = v[i][j]; out.push(o); }
  return out;
}

function readAccess_() {
  var users = {};
  rows_('Access').forEach(function (r) { if (r.email) users[String(r.email).toLowerCase()] = { role: r.role, granted_by: r.grantedBy, granted_at: r.grantedAt }; });
  return { users: users };
}
function listUsers_() {
  var out = ADMINS.map(function (a) { return { email: a.toLowerCase(), role: 'admin', granted_by: 'bootstrap' }; });
  rows_('Access').forEach(function (r) {
    if (r.email && ADMINS.map(function (a) { return a.toLowerCase(); }).indexOf(String(r.email).toLowerCase()) < 0)
      out.push({ email: String(r.email).toLowerCase(), role: r.role, granted_by: r.grantedBy, granted_at: String(r.grantedAt) });
  });
  return out;
}
function listRequests_() { return rows_('Requests').map(function (r) { return { email: String(r.email).toLowerCase(), requested_at: String(r.requestedAt), note: r.note }; }); }

function grant_(email, role, by) {
  var sh = tab_('Access'), v = sh.getDataRange().getValues(), found = -1;
  for (var i = 1; i < v.length; i++) if (String(v[i][0]).toLowerCase() === email) { found = i + 1; break; }
  var row = [email, role, by, new Date().toISOString()];
  if (found > 0) sh.getRange(found, 1, 1, 4).setValues([row]); else sh.appendRow(row);
  denyRequest_(email);
  logActivity_(by, 'grant', email + ' -> ' + role);
}
function revoke_(email) {
  var sh = tab_('Access'), v = sh.getDataRange().getValues();
  for (var i = v.length - 1; i >= 1; i--) if (String(v[i][0]).toLowerCase() === email) sh.deleteRow(i + 1);
  logActivity_(activeEmail_(), 'revoke', email);
}
function addRequest_(email, note) {
  var sh = tab_('Requests'), v = sh.getDataRange().getValues();
  for (var i = 1; i < v.length; i++) if (String(v[i][0]).toLowerCase() === email) return;
  sh.appendRow([email, new Date().toISOString(), note]);
}
function denyRequest_(email) {
  var sh = tab_('Requests'), v = sh.getDataRange().getValues();
  for (var i = v.length - 1; i >= 1; i--) if (String(v[i][0]).toLowerCase() === email) sh.deleteRow(i + 1);
}

function readTags_() { var m = {}; rows_('Tags').forEach(function (r) { if (r.threadId) m[String(r.threadId)] = String(r.tags || '').split(',').filter(Boolean); }); return m; }
function readIds_() { var m = {}; rows_('TicketIDs').forEach(function (r) { if (r.threadId) m[String(r.threadId)] = String(r.ticketId); }); return m; }
function appendIds_(newIds) { var sh = tab_('TicketIDs'); Object.keys(newIds).forEach(function (k) { sh.appendRow([k, newIds[k]]); }); }

function setTags_(threadIds, addTag, clear, user) {
  var sh = tab_('Tags'), v = sh.getDataRange().getValues();
  var map = {}; for (var i = 1; i < v.length; i++) map[String(v[i][0])] = String(v[i][1] || '').split(',').filter(Boolean);
  threadIds.forEach(function (id) {
    var cur = map[id] || [];
    if (clear) cur = [];
    else if (addTag && cur.indexOf(addTag) < 0) cur.push(addTag);
    map[id] = TAGS.filter(function (t) { return cur.indexOf(t) >= 0; });
  });
  // rewrite the tab
  sh.clearContents(); sh.appendRow(['threadId', 'tags']);
  var out = Object.keys(map).filter(function (k) { return map[k].length; }).map(function (k) { return [k, map[k].join(',')]; });
  if (out.length) sh.getRange(2, 1, out.length, 2).setValues(out);
  logActivity_(user, 'tag', (clear ? 'clear' : '+' + addTag) + ' on ' + threadIds.length + ' ticket(s)');
}

function logActivity_(user, action, detail) {
  var sh = tab_('Activity'); sh.appendRow([new Date().toISOString(), user, action, detail]);
  // trim to last 3000
  var n = sh.getLastRow(); if (n > 3001) sh.deleteRows(2, n - 3001);
}
function readActivity_(limit) {
  var r = rows_('Activity'); r.reverse();
  return { log: r.slice(0, limit).map(function (x) { return { ts: String(x.ts), user: x.user, action: x.action, detail: x.detail, thrids: [] }; }) };
}

// ------------------------------------------------------------------ mail
function sendMail_(to, subject, html) { MailApp.sendEmail({ to: to, subject: subject, htmlBody: html }); }
function notifyGranted_(email, role) {
  try {
    sendMail_(email, 'You\'ve been granted access — SalesOps portal',
      wrap_('Access granted', 'You now have <b>' + role.toUpperCase() + '</b> access.<br><br><a href="' + webUrl_()
        + '" style="background:#0d7a3f;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:700">Open portal</a>'));
  } catch (e) {}
}
function wrap_(title, body) {
  return '<div style="font-family:Segoe UI,Arial,sans-serif;color:#132a1f;max-width:560px">'
    + '<div style="background:linear-gradient(135deg,#063d24,#0d7a3f);color:#fff;padding:14px 18px;border-radius:10px">'
    + '<b style="font-size:15px">SalesOps Ticket Portal</b><div style="font-size:12px;opacity:.85">' + title + '</div></div>'
    + '<div style="padding:16px 4px;font-size:14px;line-height:1.5">' + body + '</div>'
    + '<div style="font-size:11px;color:#5d7168">Bayut KSA Operations - IS · automated message</div></div>';
}

// ------------------------------------------------------------------ trigger (optional pre-warm)
function scheduledRefresh() { refreshTickets_(); }   // add a time-driven trigger on this
