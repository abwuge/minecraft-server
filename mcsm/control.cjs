'use strict';
const fs = require('node:fs');
const crypto = require('node:crypto');
const { io } = require('/opt/mcsmanager/daemon/node_modules/socket.io-client');
const { gameConfig } = require('./bootstrap.cjs');
const roles = ['main', 'mirror', 'create', 'proxy'];
const socket = io('http://127.0.0.1:24444', {
  path: '/daemon/socket.io', transports: ['websocket'], reconnection: false, timeout: 10000
});
function request(event, data) {
  return new Promise((resolve, reject) => {
    const uuid = crypto.randomUUID();
    const timer = setTimeout(() => { socket.off(event, receive); reject(new Error(event + ' timeout')); }, 15000);
    function receive(packet) {
      if (packet.uuid !== uuid) return;
      clearTimeout(timer); socket.off(event, receive);
      packet.status === 200 ? resolve(packet.data) : reject(new Error(JSON.stringify(packet.data)));
    }
    socket.on(event, receive);
    socket.emit(event, { uuid, status: 200, event, data });
  });
}
socket.on('connect_error', error => { console.error(error.message); socket.close(); process.exitCode = 1; });
socket.on('connect', async () => {
  try {
    const key = JSON.parse(fs.readFileSync('data/Config/global.json')).key;
    if (!await request('auth', key)) throw new Error('Daemon authentication failed');
    const command = process.argv[2], requested = process.argv.slice(3);
    const services = requested.length ? requested : roles;
    if (services.some(s => !roles.includes(s))) throw new Error('Unknown game service');
    const instances = (await request('instance/overview', {}))
      .filter(i => services.includes(i.config.nickname.replace(/^mcnet-/, '')));
    if (instances.length !== services.length) throw new Error('Managed instance is missing');
    if (command === 'status') {
      console.log(JSON.stringify(instances.map(i => ({ service: i.config.nickname.slice(6),
        id: i.instanceUuid, status: i.status, processType: i.config.processType,
        cpu: i.info.cpuUsage, memory: i.info.memoryUsage }))));
    } else if (command === 'config') {
      console.log(JSON.stringify(Object.fromEntries(services.map(s => [s, gameConfig(s)]))));
    } else if (command === 'sync') {
      for (const i of instances) await request('instance/update', {
        instanceUuid: i.instanceUuid, config: gameConfig(i.config.nickname.slice(6))
      });
    } else if (command === 'start') {
      for (const i of instances) if (i.status === 0)
        await request('instance/open', { instanceUuids: [i.instanceUuid] });
    } else throw new Error('Unknown control command');
    socket.close();
  } catch (error) { console.error(error.message); socket.close(); process.exitCode = 1; }
});
