// FreightTrack patch v1 - applied 2026-03-23
// Fixes: (1) submitComment notes, (2) loadUsers Teams page, (3) loadClients empty

// ── FIX 1: submitComment ──────────────────────────────────────────────────
window.submitComment = async function() {
  var txt = document.getElementById('detail-comment-text');
  if (!txt || !txt.value.trim()) { 
    if(typeof toast === 'function') toast('Write a note first', 'error'); 
    return; 
  }
  var noteText = txt.value.trim();
  var sid = (typeof detailId !== 'undefined' && detailId) || 
            (typeof currentDetailId !== 'undefined' && currentDetailId);
  var user = typeof getUser === 'function' ? getUser() : null;
  try {
    await apiFetch('api/shipments/' + sid + '/comments', {
      method: 'POST',
      body: JSON.stringify({ author: user && user.name ? user.name : 'Agent', text: noteText })
    });
    txt.value = '';
    var ship = await apiFetch('api/shipments/' + sid);
    if(typeof renderDetail === 'function') renderDetail(ship);
    if(typeof switchDTab === 'function') switchDTab('notes');
    if(typeof toast === 'function') toast('Note added', 'success');
  } catch(e) {
    if(typeof toast === 'function') toast('Error: ' + e.message, 'error');
  }
};

// ── FIX 2: loadUsers (Teams page - was calling wrong API path) ────────────
window.loadUsers = async function() {
  var cont = document.getElementById('users-list');
  if (!cont) return;
  cont.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text2)"><i class="ph ph-spinner"></i> Loading...</div>';
  try {
    var resp = await apiFetch('api/users');
    var users = Array.isArray(resp) ? resp : (resp.data || resp.users || resp.items || []);
    if (!users.length) {
      cont.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text2);font-size:13px"><i class="ph ph-users" style="font-size:32px;display:block;margin-bottom:8px"></i>No users found</div>';
      return;
    }
    var html = '';
    users.forEach(function(u) {
      html += '<div class="card" style="margin-bottom:10px"><div class="cardbody" style="display:flex;gap:12px;align-items:flex-start;justify-content:space-between">';
      html += '<div><div style="font-weight:700;color:var(--text1)">' + (u.email||'') + '</div>';
      html += '<div style="font-size:12px;color:var(--text2);margin-top:4px">' + (u.name||'') + '</div>';
      html += '<div style="margin-top:6px"><span style="display:inline-block;background:var(--accent);color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700;text-transform:uppercase">' + u.role + '</span>';
      if (!u.isactive && !u.is_active) html += ' <span style="display:inline-block;background:#ef444420;color:#ef4444;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600">Disabled</span>';
      html += '</div></div>';
      html += '<div style="display:flex;gap:6px">';
      html += '<button onclick="toggleUser('' + u.id + '')" style="padding:6px 10px;border:1px solid var(--border);background:var(--bg2);border-radius:6px;cursor:pointer;font-size:12px">' + (u.isactive||u.is_active ? 'Disable' : 'Enable') + '</button>';
      if (u.role !== 'admin') html += '<button onclick="deleteUser('' + u.id + '')" style="padding:6px 10px;border:1px solid var(--red);background:rgba(239,68,68,.1);color:var(--red);border-radius:6px;cursor:pointer;font-size:12px">Delete</button>';
      html += '</div></div></div>';
    });
    cont.innerHTML = html;
  } catch(e) {
    cont.innerHTML = '<div style="background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);border-radius:8px;padding:12px;color:var(--red);font-size:13px">Error: ' + e.message + '</div>';
    if (typeof toast === 'function') toast(e.message, 'error');
  }
};

window.toggleUser = async function(id) {
  try { await apiFetch('api/users/' + id + '/toggle', {method:'PATCH'}); loadUsers(); }
  catch(e) { if(typeof toast==='function') toast(e.message,'error'); }
};

window.deleteUser = async function(id) {
  if (!confirm('Delete this user? This cannot be undone.')) return;
  try { await apiFetch('api/users/' + id, {method:'DELETE'}); toast('User deleted','success'); loadUsers(); }
  catch(e) { if(typeof toast==='function') toast(e.message,'error'); }
};

// ── FIX 3: loadClients (was empty because allShipments not yet loaded) ────
window.loadClients = async function() {
  if (typeof loadClientStore !== 'function') return;
  window.clients = loadClientStore();
  var ships;
  if (typeof allShipments !== 'undefined' && allShipments && allShipments.length) {
    ships = allShipments;
  } else {
    try {
      var fetched = await apiFetch('api/shipments');
      ships = Array.isArray(fetched) ? fetched : (fetched.data || fetched.shipments || []);
      window.allShipments = ships;
    } catch(e) { ships = []; }
  }
  window.clients.forEach(function(c) {
    c.shipments = ships.filter(function(s) {
      return s.client && s.client.toLowerCase().trim() === c.name.toLowerCase().trim();
    }).length;
    c.active = ships.filter(function(s) {
      return s.client && s.client.toLowerCase().trim() === c.name.toLowerCase().trim()
        && ['Confirmed','Booked','Stuffed','Sailing'].indexOf(s.status) >= 0;
    }).length;
  });
  // Auto-discover clients from shipments
  var known = window.clients.map(function(c) { return c.name.toLowerCase().trim(); });
  ships.forEach(function(sh) {
    var cn = sh.client ? sh.client.trim() : '';
    if (!cn) return;
    if (known.indexOf(cn.toLowerCase()) < 0) {
      known.push(cn.toLowerCase());
      window.clients.push({
        id: Date.now() + Math.random(), name: cn, contact: '',
        email: sh.clientemail || sh.client_email || '',
        phone: '', address: '', payment: '', notes: '',
        shipments: 0, active: 0, auto: true
      });
    }
  });
  // Re-count after discovery
  window.clients.forEach(function(c) {
    c.shipments = ships.filter(function(s) {
      return s.client && s.client.toLowerCase().trim() === c.name.toLowerCase().trim();
    }).length;
    c.active = ships.filter(function(s) {
      return s.client && s.client.toLowerCase().trim() === c.name.toLowerCase().trim()
        && ['Confirmed','Booked','Stuffed','Sailing'].indexOf(s.status) >= 0;
    }).length;
  });
  if (typeof renderClients === 'function') renderClients(window.clients);
  var cel = document.getElementById('clients-count');
  if (cel) cel.textContent = window.clients.length + ' client' + (window.clients.length !== 1 ? 's' : '');
};
