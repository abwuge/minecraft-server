// 在面板进程启动前准备节点和实例；现有管理员及其它实例保留。
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');

const roles = ['main', 'mirror', 'create', 'proxy'];
const identifier = name => crypto.createHash('md5').update('mcnet:' + name).digest('hex');
function read(file, fallback = {}) {
  return fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : fallback;
}
function write(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(value, null, 2), { mode: 0o600 });
}

function prepareDaemon(root = 'data') {
  const file = path.join(root, 'Config/global.json');
  const config = read(file);
  config.key ||= crypto.randomBytes(32).toString('hex');
  config.port = 24444;
  config.prefix = '/daemon/';
  config.enableSoftShutdown = false;
  write(file, config);
  const dir = path.join(root, 'InstanceConfig');
  fs.mkdirSync(dir, { recursive: true });
  for (const service of roles) {
    const name = 'mcnet-' + service;
    const existing = fs.readdirSync(dir).filter(f => f.endsWith('.json')).find(f => {
      const c = read(path.join(dir, f));
      return c.nickname === name && /(?:mcnet|mcsm)-container\.cjs/.test(c.startCommand || '');
    });
    const target = path.join(dir, existing || identifier(service) + '.json');
    const instance = read(target);
    Object.assign(instance, {
      nickname: name, type: 'minecraft/java', processType: 'general',
      cwd: '/mcnet-data/' + service,
      startCommand: 'node /opt/mcnet/mcsm-container.cjs ' + name,
      stopCommand: '__mcnet_stop__', stopTimeout: 70,
      terminalOption: { haveColor: true, pty: false, ptyWindowCol: 164, ptyWindowRow: 40 },
      eventTask: { autoStart: true, autoRestart: false, autoRestartMaxTimes: -1, ignore: false },
      actionCommandList: [{ name: '强制停止容器', command: '__mcnet_kill__' }],
      pingConfig: { ip: name, port: 25565, type: 1 }, tag: ['mcnet', 'compose']
    });
    write(target, instance);
  }
  console.log('[mcnet] 已配置四个 Minecraft Java 版实例');
  return config;
}

function prepareWeb(root = 'data', daemonRoot = '/mcnet-daemon-data') {
  const daemon = read(path.join(daemonRoot, 'Config/global.json'));
  if (!daemon.key) throw new Error('Daemon key is not ready');
  const dir = path.join(root, 'RemoteServiceConfig');
  fs.mkdirSync(dir, { recursive: true });
  const existing = fs.readdirSync(dir).filter(f => f.endsWith('.json'))
    .find(f => read(path.join(dir, f)).remarks === 'mcnet');
  const target = path.join(dir, existing || identifier('daemon') + '.json');
  const config = read(target);
  if (process.env.MCSM_PUBLIC_URL) {
    const url = new URL(process.env.MCSM_PUBLIC_URL);
    if (!['http:', 'https:'].includes(url.protocol)) throw new Error('MCSM_PUBLIC_URL must be HTTP(S)');
    config.ip = (url.protocol === 'https:' ? 'wss://' : 'ws://') + url.hostname;
    config.port = Number(url.port || (url.protocol === 'https:' ? 443 : 80));
  } else if (process.env.MCSM_NODE_ADDRESS) {
    config.ip = process.env.MCSM_NODE_ADDRESS;
    config.port = Number(process.env.MCSM_DAEMON_PORT || 24444);
  } else if (!config.ip) {
    config.ip = 'host.docker.internal';
    config.port = 24444;
  }
  Object.assign(config, { remarks: 'mcnet', prefix: '/daemon/', apiKey: daemon.key,
    remoteMappings: [] });
  write(target, config);
  console.log('[mcnet] 节点地址: ' + config.ip + ':' + config.port + '/daemon/');
}

function credentials() {
  const value = { username: process.env.MCSM_ADMIN_USER || 'admin',
    password: process.env.MCSM_ADMIN_PASSWORD || 'Aa1' + crypto.randomBytes(18).toString('base64url') };
  if (value.password.length < 9 || value.password.length > 36 ||
      !/(?=.*[a-z])(?=.*[A-Z])(?=.*[0-9])/.test(value.password)) {
    throw new Error('MCSM_ADMIN_PASSWORD 应为 9–36 位，并包含大小写字母和数字');
  }
  return value;
}

async function initializeAdmin() {
  const url = 'http://127.0.0.1:23333/api/auth/';
  for (let attempt = 0; attempt < 60; attempt++) {
    try {
      const status = await (await fetch(url + 'status')).json();
      if (status.status !== 200) throw new Error('Panel is not ready');
      if (status.data.isInstall) return;
      const admin = credentials();
      const result = await (await fetch(url + 'install', { method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
        body: JSON.stringify(admin) })).json();
      if (result.status !== 200) throw new Error('Administrator initialization failed');
      write('data/mcnet-credentials.json', admin);
      console.log('[mcnet] 管理员已初始化；凭据保存在 data/mcsm/web/data/mcnet-credentials.json');
      return;
    } catch (error) {
      if (attempt === 59) throw error;
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
  }
}

async function main() {
  const role = process.argv[2];
  if (role === 'daemon') prepareDaemon();
  else if (role === 'web') prepareWeb();
  else throw new Error('Expected web or daemon');
  const child = spawn(process.execPath, ['app.js', '--max-old-space-size=8192'], { stdio: 'inherit' });
  for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => child.kill(signal));
  child.on('exit', code => process.exit(code ?? 0));
  if (role === 'web') await initializeAdmin();
}
module.exports = { prepareDaemon, prepareWeb, identifier, credentials };
if (require.main === module) main().catch(error => { console.error(error.message); process.exit(1); });
