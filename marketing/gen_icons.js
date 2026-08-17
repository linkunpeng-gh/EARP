/**
 * gen_icons.js — 生成 Lucide 图标 PNG（品牌色），输出 icons.json
 * 用法: node gen_icons.js
 */
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const sharp = require('sharp');
const fs = require('fs');
const path = require('path');

const LU = require('react-icons/lu');

// 图标清单: key -> react-icons/lu 组件名
const ICONS = {
  cpu: 'LuCpu', layers: 'LuLayers', zap: 'LuZap',
  trendDown: 'LuTrendingDown', trendUp: 'LuTrendingUp',
  alert: 'LuTriangleAlert', shield: 'LuShieldCheck',
  database: 'LuDatabase', workflow: 'LuWorkflow',
  handshake: 'LuHandshake', factory: 'LuFactory',
  landmark: 'LuLandmark', car: 'LuCar', train: 'LuTrainFront',
  brain: 'LuBrain', search: 'LuSearch',
  pieChart: 'LuChartPie', barChart: 'LuChartColumn',
  fileText: 'LuFileText', dashboard: 'LuLayoutDashboard',
  sparkles: 'LuSparkles', book: 'LuBookOpen', network: 'LuNetwork',
  server: 'LuServer', clock: 'LuClock', puzzle: 'LuPuzzle',
  plug: 'LuPlug', activity: 'LuActivity', truck: 'LuTruck',
  settings: 'LuSettings', target: 'LuTarget', rocket: 'LuRocket',
  eye: 'LuEye', key: 'LuKey', lock: 'LuLock', bot: 'LuBot',
  clipboard: 'LuClipboardList', gauge: 'LuGauge',
  calendar: 'LuCalendarClock', globe: 'LuGlobe', link: 'LuLink2',
  code: 'LuCode', flask: 'LuFlaskConical', pkg: 'LuPackage',
  store: 'LuStore', card: 'LuCreditCard', arrowRight: 'LuArrowRight',
  phone: 'LuPhoneCall', mail: 'LuMail', pin: 'LuMapPin',
  bulb: 'LuLightbulb', filter: 'LuFilter', refresh: 'LuRefreshCcw',
  history: 'LuHistory', userCheck: 'LuUserCheck',
  building: 'LuBuilding2', route: 'LuRoute', scale: 'LuScale',
  fileCheck: 'LuFileCheck2', message: 'LuMessageSquare',
  messageText: 'LuMessageSquareText', listChecks: 'LuListChecks',
  send: 'LuSend', coins: 'LuCoins', percent: 'LuPercent',
  sigma: 'LuSigma', calc: 'LuCalculator', terminal: 'LuTerminal',
  users: 'LuUsers', award: 'LuAward', compass: 'LuCompass',
  check: 'LuCircleCheck', grid: 'LuLayoutGrid', loop: 'LuRefreshCw',
  bus: 'LuBus', star: 'LuStar', pen: 'LuPenLine', arrowDown: 'LuArrowDown',
  refreshCw: 'LuRefreshCw', box: 'LuBox', mic: 'LuMic', phoneCall: 'LuPhoneCall',
};

// 需要的颜色
const COLORS = {
  navy: '0E2A5C',
  blue: '0047AB',
  light: '2563EB',
  orange: 'E67E22',
  white: 'FFFFFF',
  muted: '6B7A95',
  ice: 'C9D8F2',
};

async function main() {
  const out = {};
  for (const [key, compName] of Object.entries(ICONS)) {
    const Comp = LU[compName];
    if (!Comp) {
      console.error(`MISSING icon component: ${compName} (key=${key})`);
      continue;
    }
    for (const [cname, hex] of Object.entries(COLORS)) {
      const svg = renderToStaticMarkup(
        React.createElement(Comp, { color: `#${hex}`, size: 256, strokeWidth: 2 })
      );
      const buf = await sharp(Buffer.from(svg)).png().toBuffer();
      out[`${key}_${cname}`] = 'image/png;base64,' + buf.toString('base64');
    }
    process.stdout.write(`.`);
  }
  fs.writeFileSync(path.join(__dirname, 'icons.json'), JSON.stringify(out));
  console.log(`\nDone: ${Object.keys(out).length} icons -> icons.json`);
}

main().catch((e) => { console.error(e); process.exit(1); });
