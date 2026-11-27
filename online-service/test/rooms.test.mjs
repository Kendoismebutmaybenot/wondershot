import { env } from 'cloudflare:workers';
import { describe, expect, it } from 'vitest';
import worker, {WonderRoom} from '../worker.mjs';

const call = (path, token, value, method = value === undefined ? 'GET' : 'POST') => {
  if (value && (path === '/rooms' || path.endsWith('/join'))) value = {admission:'ab'.repeat(32),...value};
  return worker.fetch(new Request('https://test' + path, {
  method, headers: { Authorization: `Bearer ${token || ''}`, 'Content-Type': 'application/json' },
  body: value === undefined ? undefined : JSON.stringify(value)
}), env);
};
async function setup() {
  const host = await (await call('/rooms', '', {})).json();
  const guest = await (await call(`/rooms/${host.code}/join`, '', {})).json();
  return { host, guest, root: `/rooms/${host.code}` };
}
describe('invite rooms', () => {
  it('fails closed when public traffic cannot be rate-limited', async () => {
    const request = new Request('https://test/rooms',{headers:{'CF-Connecting-IP':'192.0.2.1'}});
    expect((await worker.fetch(request,{...env,REQUEST_LIMIT:undefined})).status).toBe(503);
    expect((await worker.fetch(request,{...env,REQUEST_LIMIT:{limit:async()=>({success:false})}})).status).toBe(429);
  });
  it('releases a stale guest and expires a stale host through the alarm', async () => {
    const storage = new Map();
    const context = {blockConcurrencyWhile:fn=>fn(),storage:{get:async k=>storage.get(k),put:async(k,v)=>storage.set(k,v),setAlarm:async()=>{},deleteAll:async()=>storage.clear()}};
    const room = new WonderRoom(context, {...env,DIRECTORY:{getByName:()=>({fetch:async()=>Response.json({ok:true})})}});
    await room.ready;
    const result = await room.fetch(new Request('https://room/create',{method:'POST',body:JSON.stringify({code:'ab'.repeat(16),admission:'cd'.repeat(32)})}));
    expect(result.status).toBe(200);
    room.room.joined = true; room.room.seen.guest = Date.now()-31000;
    const token = room.room.guest;
    await room.alarm();
    expect(room.room.joined).toBe(false); expect(room.room.guest).not.toBe(token);
    room.room.seen.host = Date.now()-61000;
    await room.alarm();
    expect(room.room).toBe(null); expect(storage.size).toBe(0);
  });
  it('enforces a durable daily creation ceiling instead of minting unlimited sessions', async () => {
    const directory = env.DIRECTORY.getByName('budget-test-'+crypto.randomUUID());
    const permit = () => directory.fetch(new Request('https://directory/permit',{method:'POST',body:JSON.stringify({kind:'create'})}));
    for (let i=0;i<50;i++) expect((await permit()).status).toBe(200);
    expect((await permit()).status).toBe(429);
  });
  it('rejects a wrong admission proof before reserving a guest or issuing credentials', async () => {
    const host = await (await call('/rooms','',{})).json();
    const root = `/rooms/${host.code}`;
    expect((await call(root+'/join','',{admission:'cd'.repeat(32)})).status).toBe(403);
    expect((await call(root+'/ice','wrong')).status).toBe(403);
    expect((await call(root+'/join','',{})).status).toBe(200);
  });
  it('releases guest admission, rotates its token and invalidates old signaling generations', async () => {
    const {host,guest,root} = await setup();
    expect((await call(root+'/leave',guest.token,{})).status).toBe(200);
    expect((await call(root+'/ice',guest.token)).status).toBe(403);
    const replacement = await (await call(root+'/join','',{})).json();
    expect(replacement.token).not.toBe(guest.token);
    const signal = {type:'candidate',candidate:'test',mid:'0',generation:1};
    expect((await call(root+'/signals',host.token,signal)).status).toBe(409);
    signal.generation = 2;
    expect((await call(root+'/signals',host.token,signal)).status).toBe(200);
    expect((await (await call(root+'/status',replacement.token)).json()).generation).toBe(2);
    expect((await call(root+'/leave',host.token,{})).status).toBe(200);
    expect((await call(root+'/ice',host.token)).status).toBe(404);
  });
  it('gates private discovery, creation and admission before returning metadata or credentials', async () => {
    const privateEnv = {...env, PRIVATE_TEST:'true', TEST_ACCESS_KEY:'test-only-key'};
    const {host} = await setup();
    for (const [path,method] of [['/rooms','GET'],['/rooms','POST'],[`/rooms/${host.code}/join`,'POST']]) {
      const response = await worker.fetch(new Request('https://test'+path, {method,body:method==='POST'?'{}':undefined}),privateEnv);
      expect(response.status).toBe(403);
      const text = await response.text();
      expect(text).not.toContain(host.code); expect(text).not.toContain(host.token);
    }
    expect((await worker.fetch(new Request('https://test/rooms', {headers:{'X-Wonder-Test':'test-only-key'}}),privateEnv)).status).toBe(200);
  });
  it('rejects malformed and oversized creation bodies without an internal error', async () => {
    for (const body of ['{', 'null', '[]', '"string"', 'x'.repeat(1001)]) {
      expect((await worker.fetch(new Request('https://test/rooms',{method:'POST',body}),env)).status).toBe(400);
    }
  });
  it('prevents a guest claiming an empty room as host', async () => {
    const {guest,root} = await setup();
    const config = await (await call(root+'/ice',guest.token)).json();
    const lease = await (await call(root+'/acquire',guest.token,{})).json();
    const bytes = new Uint8Array(1288); new DataView(bytes.buffer).setUint32(0,config.actor,true); bytes[8+0x67]=1;
    const data = [...bytes].map(x=>x.toString(16).padStart(2,'0')).join('');
    expect((await call(root+'/commit',guest.token,{lease:lease.lease,data})).status).toBe(403);
  });
  it('rejects a duplicate persistent identity without consuming the guest slot', async () => {
    const identity = 'ab'.repeat(32);
    const host = await (await call('/rooms', '', {identity})).json();
    expect((await call(`/rooms/${host.code}/join`, '', {identity})).status).toBe(409);
    expect((await call(`/rooms/${host.code}/join`, '', {identity:'cd'.repeat(32)})).status).toBe(200);
  });
  it('lists only live room advertisements and removes a closed room', async () => {
    const {host, root} = await setup();
    const config = await (await call(root + '/ice', host.token)).json();
    const bytes = new Uint8Array(1288); new DataView(bytes.buffer).setUint32(0, config.actor, true); bytes[8 + 0x67] = 1;
    bytes.fill(0x61,8+0xa8,8+0xe8); // A guest name must never be copied into public discovery metadata.
    const data = [...bytes].map(x => x.toString(16).padStart(2,'0')).join('');
    let lease = await (await call(root + '/acquire', host.token, {})).json();
    expect((await call(root + '/commit', host.token, {lease:lease.lease,data})).status).toBe(200);
    const listing = (await (await call('/rooms')).json()).rooms.find(x => x.code === host.code);
    const publicBytes = new Uint8Array(bytes.slice(8,8+0x480)); publicBytes.fill(0,0xa8,0xe8);
    expect(listing).toEqual({code:host.code,info:[...publicBytes].map(x=>x.toString(16).padStart(2,'0')).join('')});
    lease = await (await call(root + '/acquire', host.token, {})).json();
    expect((await call(root + '/commit', host.token, {lease:lease.lease,data:'00'.repeat(1288)})).status).toBe(200);
    expect((await (await call('/rooms')).json()).rooms.some(x => x.code === host.code)).toBe(false);
  });
  it('creates private two-player rooms and rejects extra guests or unauthorized reads', async () => {
    const { host, guest, root } = await setup();
    expect(host.code).toMatch(/^[a-f0-9]{32}$/);
    expect(host.token).not.toBe(guest.token);
    expect((await call(root + '/join', '', {})).status).toBe(409);
    expect((await call(root + '/ice', 'wrong')).status).toBe(403);
    const config = await (await call(root + '/ice', host.token)).json();
    expect(config.turn).toBe(false);
    expect(config.iceServers).toEqual([{ urls: ['stun:stun.cloudflare.com:3478'] }]);
  });
  it('delivers signaling only to the other participant and isolates rooms', async () => {
    const { host, guest, root } = await setup(), other = await setup();
    const signal = { type: 'candidate', candidate: 'candidate-test', mid: '0', generation:1 };
    expect((await call(root + '/signals', host.token, signal)).status).toBe(200);
    expect((await (await call(root + '/signals?after=0', guest.token)).json()).signals).toEqual([signal]);
    expect((await (await call(root + '/signals?after=0', host.token)).json()).signals).toEqual([]);
    expect((await (await call(other.root + '/signals?after=0', other.guest.token)).json()).signals).toEqual([]);
  });
  it('serializes room updates and prevents a guest from replacing the host', async () => {
    const { host, guest, root } = await setup();
    const config = await (await call(root + '/ice', host.token)).json();
    const lease = await (await call(root + '/acquire', host.token, {})).json();
    expect((await call(root + '/acquire', guest.token, {})).status).toBe(409);
    const bytes = new Uint8Array(1288); new DataView(bytes.buffer).setUint32(0, config.actor, true); bytes[8 + 0x67] = 1;
    const encoded = [...bytes].map(x => x.toString(16).padStart(2, '0')).join('');
    expect((await call(root + '/commit', host.token, { lease: lease.lease, data: encoded })).status).toBe(200);
    const next = await (await call(root + '/acquire', guest.token, {})).json();
    expect(next.data).toBe(encoded);
    expect((await call(root + '/commit', guest.token, { lease: next.lease, data: '00'.repeat(1288) })).status).toBe(403);
  });
});
