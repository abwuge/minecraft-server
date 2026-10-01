'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {prepareDaemon, prepareWeb, credentials, gameConfig, deploymentEnv} = require('../mcsm/bootstrap.cjs');
test('control reads current deployment values instead of stale container environment', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mcnet-env-'));
  const file = path.join(root, '.env');
  try {
    fs.writeFileSync(file, '# comment\r\nWHITE_LIST=false\r\nRCON_PASSWORD=literal=$value\r\n');
    assert.equal(deploymentEnv(file).WHITE_LIST, 'false');
    assert.equal(deploymentEnv(file).RCON_PASSWORD, 'literal=$value');
    fs.writeFileSync(file, 'WHITE_LIST=true\n');
    assert.equal(deploymentEnv(file).WHITE_LIST, 'true');
  } finally { fs.rmSync(root, {recursive:true, force:true}); }
});
test('fresh panel creates four Java instances; upgrade preserves identities and data', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mcnet-test-'));
  try {
    const daemon = path.join(root,'daemon');
    const web = path.join(root,'web');
    const environment = { MCNET_DATA_PATH: '/srv/mcnet/data', ONLINE_MODE: 'true', RCON_PASSWORD: 'secret', VELOCITY_FORWARDING_SECRET: 'forward' };
    const config = prepareDaemon(daemon, environment);
    assert.ok(config.key.length >= 32);
    assert.equal(config.enableSoftShutdown, true);
    assert.equal(config.softShutdownSkipDocker, true);
    let files = fs.readdirSync(path.join(daemon,'InstanceConfig'));
    assert.equal(files.length,4);
    for (const file of files) {
      const c = JSON.parse(fs.readFileSync(path.join(daemon,'InstanceConfig',file)));
      assert.equal(c.type,'minecraft/java');
      assert.equal(c.eventTask.autoRestart,false);
      assert.equal(c.processType, 'docker');
      assert.equal(c.eventTask.autoStart, false);
      assert.equal(c.startCommand, '');
      assert.equal(c.stopCommand, '^C');
      assert.equal(c.docker.containerName, c.nickname);
      assert.ok(c.docker.extraVolumes.includes('/srv/mcnet/data/whitelist|/whitelist'));
      assert.equal(c.docker.workingDir, '');
    }
    const original = files[0];
    fs.renameSync(path.join(daemon,'InstanceConfig',original),path.join(daemon,'InstanceConfig','existing-id.json'));
    assert.equal(prepareDaemon(daemon, environment).key,config.key);
    assert.ok(fs.existsSync(path.join(daemon,'InstanceConfig','existing-id.json')));
    assert.equal(fs.readdirSync(path.join(daemon,'InstanceConfig')).length,4);
    process.env.MCSM_PUBLIC_URL='https://mcsm.example.com';
    prepareWeb(web,daemon);
    const file = path.join(web,'RemoteServiceConfig',fs.readdirSync(path.join(web,'RemoteServiceConfig'))[0]);
    const node = JSON.parse(fs.readFileSync(file));
    assert.equal(node.ip,'wss://mcsm.example.com');
    assert.equal(node.port,443);
    assert.equal(node.prefix,'/daemon/');
    assert.equal(node.apiKey,config.key);
    assert.deepEqual(node.remoteMappings,[]);
    delete process.env.MCSM_PUBLIC_URL;
    prepareWeb(web,daemon);
    assert.equal(JSON.parse(fs.readFileSync(file)).ip,node.ip);
  } finally {delete process.env.MCSM_PUBLIC_URL; fs.rmSync(root,{recursive:true,force:true});}
});

test('generated administrator passwords meet the panel policy', () => {
  for (let i=0;i<100;i++) {
    const p=credentials().password;
    assert.ok(p.length >= 9 && p.length <= 36);
    assert.match(p, /(?=.*[a-z])(?=.*[A-Z])(?=.*[0-9])/);
  }
});

test('migration preserves legacy instance IDs while replacing the ordinary-process adapter', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mcnet-migrate-'));
  const dir = path.join(root, 'InstanceConfig');
  fs.mkdirSync(dir);
  fs.writeFileSync(path.join(dir, 'legacy-id.json'), JSON.stringify({nickname:'mcnet-main',
    startCommand:'node /opt/mcnet/mcsm-container.cjs mcnet-main', processType:'general', note:'keep'}));
  try {
    prepareDaemon(root, {MCNET_DATA_PATH:'/srv/mcnet/data'});
    const c = JSON.parse(fs.readFileSync(path.join(dir,'legacy-id.json')));
    assert.equal(c.processType, 'docker');
    assert.equal(c.note, 'keep');
    assert.equal(fs.readdirSync(dir).length, 4);
  } finally {fs.rmSync(root,{recursive:true,force:true});}
});

test('native containers carry authentication, mounts, network aliases and player ports', () => {
  const env={MCNET_DATA_PATH:'/host_mnt/c/mcnet/data', IMAGE_PROXY:'local/proxy:fixed',
    PROXY_PORT:'25570', BEDROCK_PORT:'19135', ONLINE_MODE:'false', MAIN_XMX:'4G'};
  const proxy=gameConfig('proxy',env), main=gameConfig('main',env);
  assert.equal(proxy.docker.image,'local/proxy:fixed');
  assert.deepEqual(proxy.docker.ports,['25570:25565/tcp','19135:19132/udp']);
  assert.deepEqual(main.docker.ports,[]);
  assert.ok(main.docker.env.includes('XMX=4G'));
  assert.ok(main.docker.env.includes('ONLINE_MODE=false'));
  assert.ok(main.docker.env.includes('WHITE_LIST=false'));
  assert.ok(main.docker.extraVolumes.includes('/host_mnt/c/mcnet/data/main|/data'));
  assert.deepEqual(main.docker.networkAliases,['main','mcnet-main']);
});
