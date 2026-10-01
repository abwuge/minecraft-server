// MCSManager 通过 Docker API 管理已有 Compose 容器，保留其配置和数据。
'use strict';
const Docker = require('/opt/mcsmanager/daemon/node_modules/dockerode');
const readline = require('node:readline');

const name = process.argv[2];
if (!/^mcnet-[a-z0-9-]+$/.test(name || '')) throw new Error('Invalid mcnet container name');
const docker = new Docker({ socketPath: '/var/run/docker.sock' });
let current, logs, input, timer, missingSince, stopping = false, inspecting = false;

function detach() {
  logs?.destroy();
  input?.destroy();
  logs = input = undefined;
}

async function attach(info) {
  detach();
  current = docker.getContainer(info.Id);
  logs = await current.logs({ follow: true, stdout: true, stderr: true, tail: 80 });
  logs.on('error', error => console.error(error.message));
  if (info.Config.Tty) logs.pipe(process.stdout, { end: false });
  else docker.modem.demuxStream(logs, process.stdout, process.stderr);
  if (info.Config.OpenStdin) {
    input = await current.attach({ stream: true, stdin: true, stdout: false,
      stderr: false, hijack: true });
    input.on('error', error => console.error(error.message));
  }
  console.log(`[mcnet] 已连接 ${name}`);
}

async function check() {
  if (inspecting || stopping) return;
  inspecting = true;
  try {
    const info = await docker.getContainer(name).inspect();
    missingSince = undefined;
    if (info.State.Restarting) return;
    if (!info.State.Running) return finish(0);
    if (current?.id !== info.Id) await attach(info);
  } catch (error) {
    if (error.statusCode === 404) {
      // Compose 更新时会短暂移除旧容器，再用同名创建新容器。
      missingSince ??= Date.now();
      if (Date.now() - missingSince > 30000) finish(0);
      return;
    }
    console.error(error.message);
    finish(1);
  } finally { inspecting = false; }
}

function finish(code) {
  clearInterval(timer);
  detach();
  process.exit(code);
}

async function stop(force = false) {
  if (stopping) return;
  stopping = true;
  clearInterval(timer);
  try {
    // Docker stop 保留容器，并抑制 unless-stopped 策略的自动重启。
    await docker.getContainer(name).stop({ t: force ? 0 : 60 });
    finish(0);
  } catch (error) {
    if (![304, 404, 409].includes(error.statusCode)) {
      console.error(error.message);
      finish(1);
    }
    finish(0);
  }
}

readline.createInterface({ input: process.stdin, crlfDelay: Infinity }).on('line', line => {
  if (line === '__mcnet_stop__') void stop();
  else if (line === '__mcnet_kill__') void stop(true);
  else if (input) input.write(line + '\n');
  else console.error('[mcnet] 此容器未启用标准输入，请使用 RCON 或面板停止按钮。');
});
// 面板或守护进程退出时只断开连接，容器继续由 Compose 的重启策略管理。
process.on('SIGTERM', () => finish(0));
process.on('SIGINT', () => finish(0));

(async () => {
  const container = docker.getContainer(name);
  const info = await container.inspect();
  if (!info.State.Running) await container.start();
  await check();
  timer = setInterval(check, 2000);
})().catch(error => { console.error(error.message); finish(1); });
