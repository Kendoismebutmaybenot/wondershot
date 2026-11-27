const SIZE = 1288;
const ZERO = '00'.repeat(SIZE);
const TTL = 6 * 60 * 60 * 1000;
const json = (value, status = 200) => Response.json(value, { status, headers: { 'Cache-Control': 'no-store' } });
const randomToken = () => [...crypto.getRandomValues(new Uint8Array(16))].map(x => x.toString(16).padStart(2, '0')).join('');
const id = bytes => new DataView(bytes.buffer, bytes.byteOffset).getUint32(0, true);
const decode = hex => Uint8Array.from(hex.match(/../g), x => parseInt(x, 16));
const hash = async text => [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)))].map(x=>x.toString(16).padStart(2,'0')).join('');
function advertisement(hex) {
  const input = decode(hex), out = new Uint8Array(0x480);
  // Network/session identifiers, virtual host details and game advertisement only.
  // Exclude the guest's name, unused nodes and all padding/reserved bytes.
  for (const [start,end] of [[0,0x20],[0x20,0x48],[0x48,0x4c],[0x50,0x62],[0x66,0x98],[0x478,0x480]]) out.set(input.subarray(start,end),start);
  const length = input[0x26a] | input[0x26b]<<8;
  if (length > 384) throw new Error('Invalid advertisement length');
  out[0x26a] = input[0x26a]; out[0x26b] = input[0x26b];
  out.set(input.subarray(0x26c,0x26c+length),0x26c);
  return [...out].map(x=>x.toString(16).padStart(2,'0')).join('');
}

// Same two-player room transitions as the already-tested native prototype.
export function allowed(oldHex, newHex, actor) {
  if (!/^[0-9a-f]{2576}$/.test(newHex)) return false;
  if (oldHex === newHex) return true;
  const old = decode(oldHex), next = decode(newHex);
  const owner = id(old), station = id(old.subarray(4));
  const newOwner = id(next), newStation = id(next.subarray(4));
  if (!owner) return newOwner === actor && !newStation && next[8 + 0x67] === 1;
  if (owner === actor) return [0, actor].includes(newOwner) && [0, station].includes(newStation);
  if (!station && newOwner === owner && newStation === actor) {
    next.set(old.subarray(4, 8), 4);
    next[8 + 0x67] = old[8 + 0x67];
    next.set(old.subarray(8 + 0xa8, 8 + 0xe8), 8 + 0xa8);
    return next.every((x, i) => x === old[i]);
  }
  if (station === actor && newOwner === owner) {
    if (newStation === actor) return next.subarray(0, 1224).every((x, i) => x === old[i]);
    if (!newStation) {
      old.fill(0, 4, 8); old[8 + 0x67] = 1;
      old.fill(0, 8 + 0xa8, 8 + 0xe8); old.fill(0, 1224);
      return next.every((x, i) => x === old[i]);
    }
  }
  return false;
}

async function body(request, limit = 20000) {
  // Enforce the limit while reading, including chunked requests with no Content-Length.
  const reader = request.body?.getReader();
  if (!reader) throw new Error('Missing request body');
  const chunks = []; let size = 0;
  try {
    for (;;) {
      const {done, value} = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit) { await reader.cancel(); throw new Error('Request too large'); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  const result = JSON.parse(new TextDecoder('utf-8', {fatal:true}).decode(bytes));
  if (!result || typeof result !== 'object' || Array.isArray(result)) throw new Error('Expected an object');
  return result;
}

export class WonderRoom {
  constructor(ctx, env) {
    this.ctx = ctx; this.env = env;
    this.lease = null; this.signals = []; this.sequence = 0; this.ice = {};
    this.ready = ctx.blockConcurrencyWhile(async () => {
      this.room = await ctx.storage.get('room');
      this.signals = this.room?.signals || [];
      this.sequence = this.room?.sequence || 0;
    });
  }
  async save() { await this.ctx.storage.put('room', this.room); }
  async releaseGuest() {
    const data = decode(this.room.data);
    data.fill(0,4,8); data[8+0x67] = 1; data.fill(0,8+0xa8,8+0xe8); data.fill(0,1224);
    this.room.data = [...data].map(x=>x.toString(16).padStart(2,'0')).join('');
    this.room.joined = false; this.room.guest = randomToken(); this.room.generation++;
    this.room.signals = []; this.room.sequence = 0; this.signals = []; this.sequence = 0;
    this.ice = {}; this.lease = null; await this.save(); await this.publish(true);
  }
  async publish(force = false) {
    if (!this.env.DIRECTORY || !this.room?.code) return;
    if (!force && Date.now() - (this.lastPublished || 0) < 10000) return;
    const owner = parseInt(this.room.data.slice(0, 8).match(/../g).reverse().join(''), 16);
    const directory = this.env.DIRECTORY.getByName(this.room.public ? 'wonder-sw2-public-v1' : 'wonder-sw2-private-v1');
    await directory.fetch(new Request('https://directory/publish', { method: 'POST', body: JSON.stringify({
      code: this.room.code, info: owner ? advertisement(this.room.data.slice(16, 16 + 0x480 * 2)) : null
    }) }));
    this.lastPublished = Date.now();
  }
  async fetch(request) {
    await this.ready;
    const url = new URL(request.url), action = url.pathname.split('/').pop();
    try {
      if (action === 'create' && request.method === 'POST') {
        if (this.room) return json({ error: 'Room already exists' }, 409);
        const host = randomToken(), guest = randomToken();
        // Public actor IDs must not reveal any bytes of private bearer tokens.
        let hostId=0, guestId=0;
        while (!hostId) hostId=crypto.getRandomValues(new Uint32Array(1))[0];
        while (!guestId || guestId===hostId) guestId=crypto.getRandomValues(new Uint32Array(1))[0];
        const initial = await body(request, 1000);
        if (!/^[a-f0-9]{64}$/.test(initial.admission || '')) return json({error:'Missing admission proof'},400);
        const salt = randomToken();
        this.room = { host, guest, hostId, guestId, joined: false, data: ZERO, expires: Date.now() + TTL,
          code: initial.code, salt, admission: await hash(salt + initial.admission), generation:1,
          public:this.env.PRIVATE_TEST === 'false', protocol:2,
          seen:{host:Date.now(),guest:0}, identity: /^[a-f0-9]{64}$/.test(initial.identity || '') ? initial.identity : '' };
        await this.save(); await this.ctx.storage.setAlarm(Date.now()+30000);
        return json({ token: host, role: 'host' });
      }
      if (!this.room || this.room.closed || Date.now() >= this.room.expires) return json({ error: 'Room expired' }, 404);
      if (action === 'join' && request.method === 'POST') {
        const joining = await body(request, 1000);
        const now = Date.now();
        if (!this.attempts || now - this.attempts.since >= 60000) this.attempts = {since:now,count:0};
        if (++this.attempts.count > 6) return json({error:'Too many admission attempts'},429);
        if (!/^[a-f0-9]{64}$/.test(joining.admission || '') || await hash(this.room.salt + joining.admission) !== this.room.admission)
          return json({error:'Room admission denied'},403);
        if (this.room.identity && joining.identity === this.room.identity) return json({ error: 'This player identity is already hosting the room' }, 409);
        if (this.room.joined) return json({ error: 'Room already has a guest' }, 409);
        this.room.joined = true; this.room.seen.guest = Date.now(); await this.save();
        return json({ token: this.room.guest, role: 'guest' });
      }
      const bearer = request.headers.get('Authorization') || '';
      const role = bearer === `Bearer ${this.room.host}` ? 'host' :
        bearer === `Bearer ${this.room.guest}` && this.room.joined ? 'guest' : null;
      if (!role) return json({ error: 'Unauthorized' }, 403);
      this.room.seen ||= {host:Date.now(),guest:Date.now()};
      this.room.seen[role] = Date.now();
      if (Date.now() - (this.lastHeartbeatSave || 0) > 15000) { this.lastHeartbeatSave = Date.now(); await this.save(); }
      const actor = role === 'host' ? this.room.hostId : this.room.guestId;
      if (action === 'status' && request.method === 'GET') { await this.publish(); return json({generation:this.room.generation,joined:this.room.joined}); }
      if (action === 'leave' && request.method === 'POST') {
        if (role === 'host') {
          this.room.data = ZERO; await this.publish(true);
          await this.ctx.storage.deleteAll(); this.room = null; this.ice = {}; this.lease = null;
        } else {
          await this.releaseGuest();
        }
        return json({ok:true});
      }
      if (action === 'state' && request.method === 'GET') { await this.publish(); return json({ data: this.room.data }); }
      if (action === 'ice' && request.method === 'GET') {
        let iceServers = [{ urls: ['stun:stun.cloudflare.com:3478'] }];
        if (this.env.TURN_ENABLED === 'true') {
          if (!this.env.TURN_KEY_ID || !this.env.TURN_API_TOKEN) return json({ error: 'TURN is not configured' }, 503);
          if (!this.ice[role] || this.ice[role].expires < Date.now()) {
            const budget = await this.env.DIRECTORY.getByName('wonder-sw2').fetch(new Request('https://directory/permit', {method:'POST',body:JSON.stringify({kind:'turn'})}));
            if (!budget.ok) return json({error:'Online service capacity reached'},429);
            const response = await fetch(`https://rtc.live.cloudflare.com/v1/turn/keys/${this.env.TURN_KEY_ID}/credentials/generate-ice-servers`, {
              method: 'POST', redirect:'manual', headers: { Authorization: `Bearer ${this.env.TURN_API_TOKEN}`, 'Content-Type': 'application/json' },
              body: JSON.stringify({ ttl: 21600 })
            });
            if (!response.ok) return json({ error: 'TURN credentials unavailable' }, 503);
            this.ice[role] = { expires: Date.now() + TTL - 60000, servers: (await response.json()).iceServers };
          }
          iceServers = this.ice[role].servers;
        }
        return json({ actor, role, iceServers, generation:this.room.generation, turn: this.env.TURN_ENABLED === 'true' });
      }
      if (action === 'signals') {
        if (request.method === 'POST') {
          const data = await body(request, 16000);
          if (data.generation !== this.room.generation) return json({error:'Stale connection generation'},409);
          if (this.signals.length >= 128) return json({ error: 'Signaling limit reached' }, 429);
          if (!['description', 'candidate'].includes(data.type)) return json({ error: 'Invalid signal' }, 400);
          let safe;
          if (data.type === 'description') {
            if (data.kind !== (role === 'host' ? 'offer' : 'answer') || typeof data.sdp !== 'string' || data.sdp.length > 12000 ||
                this.signals.some(x=>x.role===role && x.data.type==='description')) return json({error:'Invalid description'},400);
            safe = {type:'description',kind:data.kind,sdp:data.sdp,generation:data.generation};
          } else {
            if (typeof data.candidate !== 'string' || data.candidate.length > 1024 || typeof data.mid !== 'string' || data.mid.length > 16)
              return json({error:'Invalid candidate'},400);
            safe = {type:'candidate',candidate:data.candidate,mid:data.mid,generation:data.generation};
          }
          this.signals.push({ id: ++this.sequence, role, data:safe });
          this.room.signals = this.signals; this.room.sequence = this.sequence;
          await this.save(); return json({ ok: true });
        }
        if (request.method === 'GET') {
          const after = Number(url.searchParams.get('after') || 0);
          return json({ generation:this.room.generation, cursor: this.sequence, signals: this.signals.filter(x => x.id > after && x.role !== role).map(x => x.data) });
        }
      }
      if (action === 'acquire' && request.method === 'POST') {
        if (this.lease && this.lease.until > Date.now()) return json({ error: 'Busy' }, 409);
        const token = randomToken();
        this.lease = { token, role, until: Date.now() + 5000 };
        return json({ lease: token, data: this.room.data });
      }
      if (action === 'commit' && request.method === 'POST') {
        const data = await body(request, 4000);
        if (!this.lease || this.lease.role !== role || this.lease.token !== data.lease || this.lease.until < Date.now()) return json({ error: 'Lease expired' }, 409);
        this.lease = null;
        if (role !== 'host' && id(decode(this.room.data)) === 0) return json({ error: 'Only the host can open a room' }, 403);
        if (!allowed(this.room.data, data.data, actor)) return json({ error: 'Invalid room transition' }, 403);
        this.room.data = data.data; await this.save(); await this.publish(true); return json({ ok: true });
      }
      return json({ error: 'Not found' }, 404);
    } catch { return json({ error: 'Invalid request' }, 400); }
  }
  async alarm() {
    if (!this.room) return;
    const now = Date.now();
    if (now >= this.room.expires || now - (this.room.seen?.host || 0) > 60000) {
      this.room.closed = true; this.room.data = ZERO;
      try { await this.publish(true); } catch { /* Directory entries also expire independently. */ }
      await this.ctx.storage.deleteAll(); this.room = null; this.signals = []; this.ice = {}; this.lease = null;
    } else {
      if (this.room.joined && now - (this.room.seen?.guest || 0) > 30000) await this.releaseGuest();
      await this.ctx.storage.setAlarm(now+30000);
    }
  }
}

export class WonderDirectory {
  constructor(ctx) {
    this.ctx = ctx;
    ctx.blockConcurrencyWhile(async () => { this.entries = await ctx.storage.get('entries') || {}; this.budget = await ctx.storage.get('budget') || {}; });
  }
  async fetch(request) {
    const now = Date.now();
    if (new URL(request.url).pathname === '/permit' && request.method === 'POST') {
      const {kind} = await body(request,100);
      if (!['create','turn'].includes(kind)) return json({error:'Invalid budget'},400);
      const day = Math.floor(now / 86400000);
      if (this.budget.day !== day) this.budget = {day,create:0,turn:0};
      const limit = kind === 'create' ? 50 : 100;
      if (this.budget[kind] >= limit) return json({error:'Daily capacity reached'},429);
      this.budget[kind]++; await this.ctx.storage.put('budget',this.budget);
      return json({ok:true});
    }
    for (const [code, entry] of Object.entries(this.entries)) if (now - entry.seen > 30000) delete this.entries[code];
    if (request.method === 'POST') {
      const data = await body(request, 4000);
      if (!/^[a-f0-9]{32}$/.test(data.code)) return json({ error: 'Invalid room' }, 400);
      if (data.info === null) delete this.entries[data.code];
      else {
        if (!/^[a-f0-9]{2304}$/.test(data.info)) return json({ error: 'Invalid advertisement' }, 400);
        if (!this.entries[data.code] && Object.keys(this.entries).length >= 32) return json({ error: 'Room list full' }, 429);
        this.entries[data.code] = { code: data.code, info: data.info, seen: now };
      }
      await this.ctx.storage.put('entries', this.entries);
      return json({ ok: true });
    }
    return json({ rooms: Object.values(this.entries).map(({ code, info }) => ({ code, info })) });
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === '/health' && request.method === 'GET') return json({ service: 'wondershot-rendezvous', turn: env.TURN_ENABLED === 'true' });
    const ip = request.headers.get('CF-Connecting-IP');
    if (ip) {
      const admission = request.method === 'POST' && (url.pathname === '/rooms' || url.pathname.endsWith('/join'));
      const limiter = admission ? env.ADMISSION_LIMIT : env.REQUEST_LIMIT;
      if (!limiter) return json({error:'Service unavailable'},503);
      const key = await hash(Math.floor(Date.now()/86400000) + ':' + ip);
      if (!(await limiter.limit({key})).success) return json({error:'Too many requests; try again shortly'},429);
    }
    // In a private test, discovery and guest admission require the same private access
    // as creation. A discoverable room code is not an authentication credential.
    if (env.PRIVATE_TEST !== 'false' &&
        (url.pathname === '/rooms' || /^\/rooms\/[a-f0-9]{32}\/join$/.test(url.pathname)) &&
        (!env.TEST_ACCESS_KEY || request.headers.get('X-Wonder-Test') !== env.TEST_ACCESS_KEY))
      return json({ error: 'Private test access required' }, 403);
    if (url.pathname === '/rooms' && request.method === 'GET') {
      if (!env.DIRECTORY) return json({ rooms: [] });
      return env.DIRECTORY.getByName(env.PRIVATE_TEST === 'false' ? 'wonder-sw2-public-v1' : 'wonder-sw2-private-v1').fetch(new Request('https://directory/list'));
    }
    if (url.pathname === '/rooms' && request.method === 'POST') {
      if (env.PRIVATE_TEST === 'true' && (!env.TEST_ACCESS_KEY || request.headers.get('X-Wonder-Test') !== env.TEST_ACCESS_KEY))
        return json({ error: 'Private test access required' }, 403);
      const code = randomToken();
      let initial;
      try { initial = await body(request, 1000); }
      catch { return json({ error: 'Invalid request' }, 400); }
      if (!/^[a-f0-9]{64}$/.test(initial.admission || '')) return json({error:'Missing admission proof'},400);
      if (!env.DIRECTORY) return json({error:'Service unavailable'},503);
      const budget = await env.DIRECTORY.getByName('wonder-sw2').fetch(new Request('https://directory/permit',{method:'POST',body:JSON.stringify({kind:'create'})}));
      if (!budget.ok) return json({error:'Online service capacity reached'},429);
      const room = env.ROOMS.get(env.ROOMS.idFromName(code));
      const response = await room.fetch(new Request('https://room/create', { method: 'POST', body: JSON.stringify({ code, identity: initial.identity, admission:initial.admission }) }));
      const data = await response.json();
      return json({ code, ...data }, response.status);
    }
    const match = url.pathname.match(/^\/rooms\/([0-9a-f]{32})\/(join|ice|signals|state|status|leave|acquire|commit)$/);
    if (!match) return json({ error: 'Not found' }, 404);
    const room = env.ROOMS.get(env.ROOMS.idFromName(match[1]));
    return room.fetch(new Request(`https://room/${match[2]}${url.search}`, request));
  }
};
