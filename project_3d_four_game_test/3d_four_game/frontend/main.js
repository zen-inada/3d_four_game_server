// ===== Three.js & Controls =====
import * as THREE from '/static/three/build/three.module.js';
import { OrbitControls } from '/static/three/examples/jsm/controls/OrbitControls.js';

// ================== 定数 ==================
const BASE_URL = 'http://35.74.10.149:8001';

// ================== ヘルパ ==================

// === 合法手チェック ===
function isColumnFull(board, x, y) {
  // z=0..3 のどこかに 0（空き）があれば「満杯ではない」
  for (let z = 0; z < 4; z++) {
    if (board[z][y][x] === 0) return false;
  }
  return true;
}
function findFirstEmptyXY(board) {
  for (let y = 0; y < 4; y++) {
    for (let x = 0; x < 4; x++) {
      for (let z = 0; z < 4; z++) {
        if (board[z][y][x] === 0) return { x, y };
      }
    }
  }
  return null; // もう空きがない
}

// ==== クリック連打＆多重起動を吸収するガード ====
let _clickBusy = false;           // 同時実行ガード
let _lastClickAt = 0;             // 連打スロットル
const CLICK_GAP_MS = 250;

function clickGate() {
  const now = Date.now();
  if (_clickBusy) return false;
  if (now - _lastClickAt < CLICK_GAP_MS) return false;
  _lastClickAt = now;
  return true;
}
function setClickBusy(v) { _clickBusy = !!v; }

// === 通信の一括キャンセル＆世代管理（※この定義はファイル内で1回だけ） ===
let _reqController = new AbortController(); // 共通 signal
let _epoch = 0;                             // 世代（リセット/停止で++）

function _bumpEpochAndAbortAll() {
  try { _reqController.abort(); } catch { }
  _reqController = new AbortController();
  _epoch++;
}
function _snapEpochAndGameId() {
  return { epoch: _epoch, gid: currentGameId };
}

// Abort（ユーザー操作の中断）はエラー表示しないための判定（※1回だけ定義）
function isAbortError(err) {
  const name = err?.name || "";
  const msg = String(err?.message || err || "");
  return name === "AbortError" || /aborted/i.test(msg) || /AbortError/i.test(msg);
}

// fetch ヘルパ（JSON）— 常に共通 signal を付与（※1回だけ定義）
async function fetchJSON(url, init = {}) {
  const signal = init.signal ?? _reqController.signal;
  const r = await fetch(url, { ...init, signal });
  let data = null;
  try { data = await r.json(); } catch { }
  if (!r.ok) {
    const msg = data?.detail || data?.message || r.statusText || "Network error";
    throw new Error(msg);
  }
  return data ?? {};
}

// 理由の抽出＆整形（末尾の「→ 空きセル…」を切り落として要点だけ）
const extractReason = (resp) => resp?.reason || resp?.message || null;
const fmtReason = (reason, max = 200) => {
  if (!reason) return "";
  let s = String(reason);
  s = s.replace(/\s*→\s*空きセル.*$/u, ""); // ノイズを削る
  const m =
    s.match(/(banned [^)\n]+|this builtin is disabled|ModuleNotFoundError:[^\n）]+|AI出力不正[^\n）]*)/i) ||
    s.match(/RuntimeError:\s*([^\n]+)/i) ||
    s.match(/ValueError:\s*([^\n]+)/i);
  if (m) s = m[0];
  return `  ※${s.split("\n")[0].trim()}`.slice(0, max);
};

function normalizePathOrName(input) {
  if (!input) return '';
  return String(input).trim().replace(/\\/g, '/');
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
function getAutoSpeed() {
  return parseInt(document.getElementById("autoSpeed")?.value) || 500;
}

// ============== Users API ==============
async function fetchUsers() { return await fetchJSON(`${BASE_URL}/users`); }
async function registerUser(name, path) {
  return await fetchJSON(`${BASE_URL}/users`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, path })
  });
}
async function renameUser(id, name) {
  return await fetchJSON(`${BASE_URL}/users/${id}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name })
  });
}
async function deleteUser(id) {
  return await fetchJSON(`${BASE_URL}/users/${id}`, { method: "DELETE" });
}

// ============== 試合履歴まわり ==============
let currentMatch = 1;
let matchResults = [];
let currentGameId = null;

function updateMatchHistory() {
  const tbody = document.querySelector("#matchHistory tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  matchResults.forEach((r, i) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${i + 1}戦目</td><td>${r.winner}</td><td>${r.moves}</td>`;
    tbody.appendChild(tr);
  });
}

// 先手ラジオに合わせて Player番号→セレクトID を切替えてチーム名取得
function getTeamNameByPlayerNumber(n) {
  const first = document.querySelector('input[name="firstPlayer"]:checked')?.value || "ai1";
  const selectId = (first === "ai1")
    ? (n === 1 ? "ai1Select" : "ai2Select")
    : (n === 1 ? "ai2Select" : "ai1Select");
  const select = document.getElementById(selectId);
  const opt = select?.selectedOptions?.[0] || select?.options?.[0];
  return (opt && opt.textContent) ? opt.textContent : `Player ${n}`;
}

function showFinalResult() {
  if (matchResults.length < 2) return;
  const resultDiv = document.getElementById("finalResult");
  const [m1, m2] = matchResults;
  let finalWinner = null;
  if (m1.winner === m2.winner) finalWinner = m1.winner;
  else if (m1.moves < m2.moves) finalWinner = m1.winner;
  else if (m2.moves < m1.moves) finalWinner = m2.winner;
  else finalWinner = getTeamNameByPlayerNumber(2); // 同手数なら後手勝ち
  if (resultDiv) resultDiv.textContent = `🏆 最終勝者: ${finalWinner}`;
}

// 2戦制の片方終了時に呼ぶ
async function handleMatchEnd(winnerNumber, moves) {
  let num = Number(winnerNumber);
  if (isNaN(num) && typeof winnerNumber === "string") {
    if (winnerNumber.includes("1")) num = 1;
    else if (winnerNumber.includes("2")) num = 2;
  }
  let winnerLabel = "引き分け";
  if (num === 1 || num === 2) winnerLabel = getTeamNameByPlayerNumber(num);
  matchResults.push({ winner: winnerLabel, moves });
  updateMatchHistory();

  if (currentMatch === 1) {
    currentMatch = 2;
    const btn = document.getElementById("nextMatchButton");
    if (btn) btn.style.display = "inline-block";
    setStatusText("1戦目終了。『次の試合』で2戦目を開始できます。");
  } else {
    showFinalResult();
  }
}

// ================== Three.js セットアップ ==================
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 1000);
camera.position.set(6, 8, 10);
camera.lookAt(0, 0, 0);

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setSize(window.innerWidth, window.innerHeight);
document.body.appendChild(renderer.domElement);

// ライト
const light = new THREE.DirectionalLight(0xffffff, 1);
light.position.set(5, 15, 5);
scene.add(light);

// 木目テクスチャの台座とポスト
const textureLoader = new THREE.TextureLoader();
const woodTexture = textureLoader.load('/static/textures/Wood026_2K-JPG_Color.jpg');
woodTexture.wrapS = woodTexture.wrapT = THREE.RepeatWrapping;
woodTexture.repeat.set(2, 2);

const baseGeometry = new THREE.BoxGeometry(4.5, 0.2, 4.5);
const baseMaterial = new THREE.MeshStandardMaterial({ map: woodTexture });
const base = new THREE.Mesh(baseGeometry, baseMaterial);
base.position.y = -0.1;
scene.add(base);

const postGeometry = new THREE.CylinderGeometry(0.05, 0.05, 3.2, 16);
const postMaterial = new THREE.MeshStandardMaterial({ map: woodTexture });
const clickablePosts = [];
for (let x = 0; x < 4; x++) {
  for (let z = 0; z < 4; z++) {
    const post = new THREE.Mesh(postGeometry, postMaterial);
    post.position.set(x - 1.5, 1.6, z - 1.5);
    post.userData = { x, y: z };
    scene.add(post);
    clickablePosts.push(post);
  }
}

// 操作
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.05;

// レンダリングループ
function animate() {
  controls.update();
  renderer.render(scene, camera);
}
renderer.setAnimationLoop(animate);
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

// ================== 盤表示 ==================
const blackMaterial = new THREE.MeshStandardMaterial({ color: 0x000000 });
const whiteMaterial = new THREE.MeshStandardMaterial({ color: 0xffffff });
const sphereGeometry = new THREE.SphereGeometry(0.4, 32, 32);

let pieces = [];
let blinkingPieces = [];
let blinkOn = true;
setInterval(() => {
  blinkingPieces.forEach(p => p.visible = blinkOn);
  blinkOn = !blinkOn;
}, 300);

function updateBoardVisual(board, winningCoords = null) {
  for (const p of pieces) scene.remove(p);
  pieces = [];
  blinkingPieces = [];

  for (let z = 0; z < 4; z++) {
    for (let y = 0; y < 4; y++) {
      for (let x = 0; x < 4; x++) {
        const cell = board[z][y][x];
        if (!cell) continue;
        const material = (cell === 1 ? blackMaterial : whiteMaterial).clone();
        const sphere = new THREE.Mesh(sphereGeometry, material);
        sphere.position.set(x - 1.5, 0.4 + z * 0.79, y - 1.5);
        scene.add(sphere);
        pieces.push(sphere);

        if (winningCoords?.some(([wx, wy, wz]) => wx === x && wy === y && wz === z)) {
          blinkingPieces.push(sphere);
        }
      }
    }
  }
}

// ================== ステータス表示 ==================
function setStatusText(text) {
  const status = document.getElementById('statusMessage');
  if (status) status.textContent = text;
  const turnDisplay = document.getElementById('turnDisplay');
  if (turnDisplay) {
    if (text.includes('Player 1')) turnDisplay.textContent = 'Player 1';
    else if (text.includes('Player 2')) turnDisplay.textContent = 'Player 2';
  }
}

// ================== サーバ盤面取得 ==================
// === サーバ盤面取得（UI反映は最新世代だけ） ===
async function getBoard() {
  if (!currentGameId) throw new Error("game_idが未設定です");
  const { epoch, gid } = _snapEpochAndGameId();

  const data = await fetchJSON(`${BASE_URL}/games/${gid}`);

  // ★ リセット等で世代やIDが変わっていたら UI 反映しない
  if (epoch !== _epoch || gid !== currentGameId) {
    return data; // 呼び出し元で必要なら参照だけ
  }

  updateBoardVisual(data.board, data.winning_coords);
  setStatusText(`Player ${data.current_player}'s turn`);
  return data;
}

// ================== 入力（手動） ==================
const raycaster = new THREE.Raycaster();
const mouse = new THREE.Vector2();
let isAutoRunning = false;
let isAutoPlaying = false;
let isBusy = false; // 操作中フラグ

// クリックは 1 本に統合（オート/ビジー時は弾く）
// ================== 入力（手動：クリック） ==================
window.addEventListener('click', async (event) => {
  // オート中 or 忙しい間は無視
  if (isAutoPlaying || isBusy) return;
  // 連打ガード（250ms以内の連打や同時実行を弾く）
  if (!clickGate()) return;

  try {
    setClickBusy(true);

    const rect = renderer.domElement.getBoundingClientRect();
    mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

    raycaster.setFromCamera(mouse, camera);
    const intersects = raycaster.intersectObjects(clickablePosts);
    if (intersects.length > 0) {
      const { x, y } = intersects[0].object.userData;
      await postMove(x, y); // 内部で世代/IDチェック
    }
  } finally {
    setClickBusy(false);
  }
});


// ================== タイマー ==================
let timerInterval = null;
let remainingTime = 30;

function getSelectedTime() {
  return parseInt(document.getElementById('timeSelect')?.value) || 30;
}
function updateTimerDisplay() {
  const timer = document.getElementById('timerDisplay');
  if (timer) timer.textContent = `${remainingTime}s`;
}
function startTurnTimer(onTimeout = autoMove) {
  clearInterval(timerInterval);
  remainingTime = getSelectedTime();
  updateTimerDisplay();
  timerInterval = setInterval(() => {
    remainingTime--;
    updateTimerDisplay();
    if (remainingTime <= 0) {
      clearInterval(timerInterval);
      onTimeout();
    }
  }, 1000);
}
function stopTimer(resetDisplay = true) {
  clearInterval(timerInterval);
  if (resetDisplay) {
    remainingTime = getSelectedTime();
    updateTimerDisplay();
  }
}

// ================== ログ ==================
function addMoveLog(moveCount, teamName, playerNumber, x, y, reason /* 省略可 */) {
  const log = document.getElementById("logMessages");
  if (!log) return;
  const p = document.createElement("p");
  const color = playerNumber === 1 ? "黒" : "白";
  p.textContent = `${moveCount}手目  ${teamName} : ${color} : (${x}, ${y})`;
  if (reason) {
    const span = document.createElement("span");
    span.className = "reason";
    span.textContent = fmtReason(reason);
    p.appendChild(span);
  }
  log.appendChild(p);
  log.scrollTop = log.scrollHeight;
}

function logMessage(text) {
  const log = document.getElementById("logMessages");
  if (!log) return;
  const p = document.createElement("p");
  p.textContent = text;
  log.appendChild(p);
  log.scrollTop = log.scrollHeight;
}

// ================== アルゴパス解決 ==================
function getAlgoPath(basePath) {
  if (!basePath || typeof basePath !== "string" || basePath.trim() === "") return null;
  const normalized = basePath.trim().replace(/\\/g, '/');
  if (normalized.toLowerCase().endsWith(".py")) return normalized;
  return normalized.endsWith("/") ? normalized + "main.py" : normalized + "/main.py";
}

function getSelectedAIPathsByRadio() {
  const first = document.querySelector('input[name="firstPlayer"]:checked')?.value || "ai1";
  const ai1Select = document.getElementById("ai1Select");
  const ai2Select = document.getElementById("ai2Select");
  const ai1 = normalizePathOrName(ai1Select?.value);
  const ai2 = normalizePathOrName(ai2Select?.value);
  const base1 = first === "ai1" ? ai1 : ai2;
  const base2 = first === "ai1" ? ai2 : ai1;
  const p1 = getAlgoPath(base1);
  const p2 = getAlgoPath(base2);
  if (!p1 || !p2) {
    console.error("❌ AIパスが未設定または無効です:", { base1, base2 });
    alert("⚠️ 先手・後手のAIを正しく選択してください。");
    return null;
  }
  return { p1, p2 };
}

// ================== 勝敗/継続の一元ハンドラ ==================
/**
 * @param {object} data サーバからの応答(JSON)
 * @param {object} opts { mode: 'manual'|'step'|'auto', restartTimerOnOk?: boolean, reason?: string, suppressLog?: boolean }
 * @returns { finished: boolean }
 */
async function handleServerResult(data, opts = {}) {
  const { mode = 'manual', restartTimerOnOk = false, reason = null, suppressLog = false } = opts;

  // 可視更新（いつでも board があれば）
  if (data.board) updateBoardVisual(data.board, data.winning_coords);

  // 「直前に打った側」を推定（current_player は通常「次の手番」）
  const mover = (typeof data.winner === "number")
    ? data.winner
    : (typeof data.player === "number" ? data.player
      : (typeof data.player === "string" && data.player.includes("1")) ? 1
        : (typeof data.player === "string" && data.player.includes("2")) ? 2
          : (typeof data.current_player === "number" ? (3 - data.current_player) : null));

  // 最後の手座標をできるだけ拾う
  const last = data.last_move ?? data.move ?? null;
  const x = last?.x ?? "?";
  const y = last?.y ?? "?";

  const moveCount = data.move_count ?? data.moves ?? data.turn_count ?? "?";
  const teamName = (mover === 1 || mover === 2) ? getTeamNameByPlayerNumber(mover) : "Unknown";

  // 理由（優先：opts.reason → data.reason）
  const finalReason = reason || data.reason || null;

  // --- 分岐 ---
  if (data.status === "ok") {
    if (!suppressLog && (mover === 1 || mover === 2))
      addMoveLog(moveCount, teamName, mover, x, y, finalReason);
    setStatusText(`Player ${data.current_player}'s turn`);
    if (restartTimerOnOk && !isAutoPlaying) startTurnTimer();
    return { finished: false };
  }

  if (data.status === "win") {
    console.log(data.winner + " | " + data.player)
    const winnerNum = (typeof data.winner === "number") ? data.winner
      : (typeof data.player === "number") ? data.player
        : (String(data.player || "").includes("1") ? 1 : 2);
    const winnerTeam = getTeamNameByPlayerNumber(Number(winnerNum));
    console.log(teamName + " | " + mover)

    const logPlayer = (mover === 1 || mover === 2) ? mover : winnerNum;
    const logTeam = (mover === 1 || mover === 2) ? teamName : winnerTeam;
    console.log(logPlayer + " | " + logTeam)
    if (!suppressLog) addMoveLog(moveCount, logTeam, logPlayer, x, y, finalReason);

    setStatusText(`🏆 ${winnerTeam} 勝利!`);
    stopTimer(false);
    disablePlayButtons();
    logMessage(`🎉 ${winnerTeam} が ${moveCount}手で勝利！`);
    alert(`🏆 ${winnerTeam} wins! (${moveCount}手)`);
    await handleMatchEnd(winnerNum, moveCount);
    return { finished: true };
  }

  if (data.status === "draw") {
    if (!suppressLog && (mover === 1 || mover === 2))
      addMoveLog(moveCount, teamName, mover, x, y, finalReason);
    setStatusText("🤝 引き分け！");
    stopTimer(false);
    disablePlayButtons();
    logMessage("🤝 引き分けになりました");
    alert("🤝 引き分け！");
    await handleMatchEnd("引き分け", 999);
    return { finished: true };
  }

  if (data.status === "invalid") {
    setStatusText(`❌ ${data.message || "Invalid move"}`);
    return { finished: false };
  }

  if (data.status === "finished") {
    setStatusText("✅ ゲーム終了");
    stopTimer(false);
    disablePlayButtons();
    return { finished: true };
  }

  if (data.status === "error") {
    setStatusText(`⚠️ エラー: ${data.message || ""}`);
    stopTimer(false);
    alert(`⚠️ エラー: ${data.message || ""}`);
    return { finished: true };
  }

  // 不明レスポンス
  setStatusText("⚠️ 未知のレスポンス");
  return { finished: false };
}

// ================== 手動：駒を置く ==================
async function postMove(x, y) {
  if (!currentGameId) await startNewGame();
  const { epoch, gid } = _snapEpochAndGameId();

  // この処理中は手動入力をブロック（多重POST防止）
  isBusy = true;
  try {
    const data = await fetchJSON(`${BASE_URL}/games/${gid}/move`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ x, y })
    });

    // リセット/別ゲーム切替が起きていたら捨てる
    if (epoch !== _epoch || gid !== currentGameId) return { finished: true };

    return await handleServerResult(data, { mode: 'manual', restartTimerOnOk: true });
  } finally {
    isBusy = false;
  }
}


// ================== UI初期化 ==================
function populateTimeOptions() {
  const select = document.getElementById('timeSelect');
  if (!select) return;
  for (let i = 1; i <= 120; i++) {
    const option = document.createElement('option');
    option.value = i;
    option.textContent = `${i} 秒`;
    select.appendChild(option);
  }
  select.value = '30';
}
populateTimeOptions();

function setButtonsEnabled(enabled) {
  isBusy = !enabled;
  // ステップは従来どおり制御
  const stepBtn = document.getElementById("stepButton");
  if (stepBtn) stepBtn.disabled = !enabled;

  // リセットは「常に押せる」。ただしオート中だけは無効化。
  const resetBtn = document.getElementById("resetButton");
  if (resetBtn) {
    resetBtn.disabled = (isAutoRunning || isAutoPlaying) ? true : false;
  }
}

// === リセット（押下後は即UIを更地に。通信は裏で） ===
document.getElementById('resetButton')?.addEventListener('click', () => {
  // 進行中の処理を即無効化（使っていなければこの2行は無視してOK）
  if (typeof _bumpEpochAndAbortAll === 'function') _bumpEpochAndAbortAll();
  if (typeof stepToken !== 'undefined') stepToken++;

  // タイマー/状態フラグを止める
  stopTimer();
  isAutoRunning = false;
  isAutoPlaying = false;

  // 🔽 ここで Auto ボタンの表示を初期化
  const autoBtn = document.getElementById('autoButton');
  if (autoBtn) {
    autoBtn.textContent = 'オート開始';
    autoBtn.setAttribute('aria-pressed', 'false');
    autoBtn.disabled = false; // 念のため有効化
  }

    // 🔽 ★ ステップ・オートボタンを有効化し直す
  enablePlayButtons();

  // 試合履歴・UIを即リセット
  currentMatch = 1;
  matchResults = [];
  updateMatchHistory();

  const fr = document.getElementById("finalResult");
  if (fr) fr.textContent = "";
  const log = document.getElementById("logMessages");
  if (log) log.innerHTML = "";
  clearBoardVisual();
  setStatusText("♻️ リセットしました");

  // サーバ側は裏で処理（待たない）
  (async () => {
    try {
      if (currentGameId) {
        await fetchJSON(`${BASE_URL}/games/${currentGameId}`, { method: 'DELETE' });
      }
      await startNewGame();
      const init = await getBoard();
      setStatusText(`Player ${init.current_player}'s turn`);
    } catch (e) {
      console.warn("リセット時のサーバ処理失敗:", e);
    }
  })();
});

// --- 手番の“世代番号”で遅延レス競合を防ぐ ---
let stepToken = 0;

// ==== ステップ実行（オート中は弾く／満杯列はフォールバック） ====
document.getElementById('stepButton')?.addEventListener('click', async () => {
  // オートが走っている間はステップ禁止（競合回避）
  if (isAutoRunning || isAutoPlaying) {
    setStatusText("🛑 オート中はステップできません（オート停止してください）");
    return;
  }
  if (!clickGate()) return;

  setButtonsEnabled(false);
  const myToken = ++stepToken;

  try {
    if (!currentGameId) await startNewGame();

    // タイムアウト時の左上フォールバック（既存ロジック）
    startTurnTimer(async () => {
      if (myToken !== stepToken) return;
      await autoMove();
      stepToken++;
    });

    // 直近の盤面を取得してから思考
    const boardData = await getBoard();
    const current = boardData.current_player;

    // AIパス解決
    const paths = getSelectedAIPathsByRadio();
    const algoPath = current === 1 ? paths.p1 : paths.p2;
    if (!algoPath) {
      stopTimer(false);
      alert("⚠️ アルゴリズムのパスが未設定です。先手・後手のAIを選択してください。");
      return;
    }

    // 思考（/algo-move）
    const timeLimit = getSelectedTime(); // ← 既に定義済みの関数
    const resp = await fetchJSON(`${BASE_URL}/games/${currentGameId}/algo-move`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        player_id: `player${current}`,
        board: boardData.board,
        algorithmPath: algoPath,
        timeLimit: timeLimit   // ★追加
      })
    });

    if (myToken !== stepToken) { stopTimer(false); return; }

    // 提案手
    let { x, y } = resp.move || {};
    let stepReason = extractReason(resp);

    // ★ 合法チェック：列が満杯ならフォールバックへ差し替え
    if (Number.isInteger(x) && Number.isInteger(y) && isColumnFull(boardData.board, x, y)) {
      const fb = findFirstEmptyXY(boardData.board);
      if (fb) {
        x = fb.x; y = fb.y;
        stepReason = (stepReason ? `${stepReason} / ` : "") + "無効座標を返したため、強制配置";
      } else {
        // 置く場所が本当に無い（盤面フル）→安全に終了
        stopTimer(false);
        setStatusText("⛔ 置けるマスがありません（盤面が満杯）");
        return;
      }
    }

    // 実際に着手
    const moveResult = await fetchJSON(`${BASE_URL}/games/${currentGameId}/move`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ x, y })
    });
    if (myToken !== stepToken) { stopTimer(false); return; }

    stopTimer(false);

    // ⚠️ invalid はログしないで終了（変な軌道/表示を避ける）
    if (moveResult?.status === "invalid") {
      setStatusText(`❌ 無効な手でした（再試行してください）`);
      return;
    }

    // ログ＆UI（有効手のみ）
    const moved = (typeof moveResult.current_player === "number") ? (3 - moveResult.current_player) : current;
    const moveCount = moveResult.move_count ?? moveResult.moves ?? moveResult.turn_count ?? "?";
    addMoveLog(moveCount, getTeamNameByPlayerNumber(moved), moved, x, y, stepReason);

    const { finished } = await handleServerResult(moveResult, {
      mode: 'step', restartTimerOnOk: false, reason: stepReason, suppressLog: true
    });
    if (!finished) setStatusText(`Player ${moveResult.current_player}'s turn`);

    stepToken++;
  } catch (e) {
    if (!isAbortError(e)) setStatusText(`⚠️ /algo-move エラー: ${e.message || e}`);
    stopTimer(false);
  } finally {
    setButtonsEnabled(true);
  }
});


// === Autoボタン ===
const autoBtn = document.getElementById('autoButton');

function updateAutoButton() {
  if (!autoBtn) return;
  autoBtn.textContent = isAutoRunning ? "オート停止" : "オート開始";
  autoBtn.setAttribute("aria-pressed", isAutoRunning ? "true" : "false");
}

// ★ オート専用クールダウン管理
let _autoCooldownUntil = 0;
const AUTO_COOLDOWN_MS = 20; // 1.2秒 (連打防止)

function autoClickAllowed() {
  return Date.now() >= _autoCooldownUntil;
}
function applyAutoCooldown(ms = AUTO_COOLDOWN_MS) {
  _autoCooldownUntil = Date.now() + ms;
  if (autoBtn) {
    autoBtn.disabled = true;
    setTimeout(() => { autoBtn.disabled = false; }, ms);
  }
}

// ボタンクリック → runAutoLoop に丸投げ
autoBtn?.addEventListener('click', (e) => {
  e.preventDefault();
  if (!autoClickAllowed()) return; // 連打防止
  applyAutoCooldown();
  runAutoLoop(); // ← トグル処理は内部で管理
});


// === オート処理 (/auto-step で1手ずつ) ===
let _autoLoopBusy = false; // 起動中の多重防止

async function runAutoLoop() {
  // ---- 停止トグル ----
  if (isAutoRunning) {
    //_bumpEpochAndAbortAll();  // 進行中の通信を中断
    isAutoRunning = false;
    isAutoPlaying = false;
    setStatusText("🛑 オートモード解除");
    stopTimer(false);         // タイマーも止める
    updateAutoButton();
    return;
  }

  // ---- 開始パス ----
  if (_autoLoopBusy) return;  // 二重起動防止
  _autoLoopBusy = true;

  try {
    if (!currentGameId) await startNewGame();
    isAutoRunning = true;
    isAutoPlaying = true;
    stopTimer(false);         // 念のため初期停止
    updateAutoButton();

    const paths = (typeof getSelectedAIPathsByRadio === "function") ? getSelectedAIPathsByRadio() : null;
    if (!paths) {
      alert("⚠️ オート用のAIが未設定です。");
      isAutoRunning = false;
      isAutoPlaying = false;
      updateAutoButton();
      return;
    }
    const p1 = paths.p1, p2 = paths.p2;

    const { epoch, gid } = _snapEpochAndGameId();

    try {
      // 初期同期
      const initState = await fetchJSON(`${BASE_URL}/games/${gid}`);
      if (epoch !== _epoch || gid !== currentGameId) return;
      updateBoardVisual(initState.board);
      setStatusText(`Player ${initState.current_player}'s turn`);

      // ループ
      while (isAutoRunning) {
        if (epoch !== _epoch || gid !== currentGameId) break;

        // UI間隔（0でもOK）
        await new Promise(r => setTimeout(r, getAutoSpeed()));
        if (epoch !== _epoch || gid !== currentGameId) break;

        // 思考中だけタイマーを動かす（タイムアウト時は no-op）
        stopTimer(false);
        startTurnTimer(() => { /* no-op: オートでは何もしない */ });

        // 1手だけサーバに進めてもらう
        const data = await fetchJSON(`${BASE_URL}/games/${gid}/auto-step`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            player1: p1,
            player2: p2,
            timeLimit: getSelectedTime()
          })
        });

        stopTimer(false); // 思考完了 → タイマー停止

        // ログ
        const moved = (typeof data.current_player === "number") ? (3 - data.current_player) : null;
        const lm = data.last_move ?? data.move ?? null;
        const mx = lm?.x ?? "?";
        const my = lm?.y ?? "?";
        const reason = (typeof extractReason === "function") ? extractReason(data) : null;
        const mvCount = data.move_count ?? data.moves ?? data.turn_count ?? "?";
        if (moved === 1 || moved === 2) {
          addMoveLog(mvCount, getTeamNameByPlayerNumber(moved), moved, mx, my, reason);
        }

        const { finished } = await handleServerResult(
          data, { mode: "auto", restartTimerOnOk: false, reason, suppressLog: true }
        );
        if (finished) break;
        if (!isAutoRunning || epoch !== _epoch || gid !== currentGameId) break;
      }
    } catch (e) {
      if (typeof isAbortError !== "function" || !isAbortError(e)) {
        setStatusText(`⚠️ Auto進行エラー: ${e.message || e}`);
        alert(`⚠️ Auto進行エラー: ${e.message || e}`);
      }
    }
  } finally {
    stopTimer(false);
    isAutoRunning = false;
    isAutoPlaying = false;
    updateAutoButton();
    _autoLoopBusy = false;
  }
}

// ================== クローン/チーム管理 ==================
const clonedTeams = [];  // [{ id, name, path }]

function updateAISelectors() {
  const ai1Select = document.getElementById("ai1Select");
  const ai2Select = document.getElementById("ai2Select");
  [ai1Select, ai2Select].forEach(select => {
    if (!select) return;
    select.innerHTML = "";
    clonedTeams.forEach(({ id, name, path }) => {
      const option = document.createElement("option");
      option.value = path;         // value は実パス
      option.textContent = name;   // 表示はチーム名
      option.dataset.userId = id;
      select.appendChild(option);
    });
  });
}

function renderTeamList() {
  const ul = document.getElementById("teamList");
  if (!ul) return;
  ul.innerHTML = "";
  clonedTeams.forEach((team, index) => {
    const li = document.createElement("li");

    const input = document.createElement("input");
    input.type = "text";
    input.value = team.name;
    input.style.marginRight = "10px";
    input.addEventListener("change", async () => {
      try {
        const updated = await renameUser(team.id, input.value.trim());
        clonedTeams[index].name = updated.name;
        updateAISelectors();
      } catch (e) {
        alert("名前変更に失敗: " + (e.message || e));
      }
    });

    const delBtn = document.createElement("button");
    delBtn.textContent = "🗑️";
    delBtn.style.marginLeft = "5px";
    delBtn.addEventListener("click", async () => {
      try {
        await deleteUser(team.id);
        clonedTeams.splice(index, 1);
        updateAISelectors();
        renderTeamList();
      } catch (e) {
        alert("削除に失敗: " + (e.message || e));
      }
    });

    li.appendChild(input);
    li.appendChild(delBtn);
    ul.appendChild(li);
  });
}

document.getElementById("clonebtn")?.addEventListener("click", async (e) => {
  e.preventDefault();
  const repoUrl = document.getElementById("repoUrl")?.value.trim();
  const teamName = document.getElementById("teamName")?.value.trim();
  const resultArea = document.getElementById("cloneResult");

  if (!repoUrl || !teamName) {
    if (resultArea) resultArea.textContent = "⚠️ URLとチーム名を両方入力してください";
    return;
  }

  try {
    const res = await fetch(`${BASE_URL}/clone`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repo_url: repoUrl })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "クローン失敗");

    const newPath = data.path;
    const created = await registerUser(teamName, newPath);

    const idx = clonedTeams.findIndex(t => t.path === created.path);
    const row = { id: created.id, name: created.name, path: created.path };
    if (idx >= 0) clonedTeams[idx] = row; else clonedTeams.push(row);

    updateAISelectors();
    renderTeamList();

    const ai1Select = document.getElementById("ai1Select");
    const ai2Select = document.getElementById("ai2Select");
    if (ai1Select && !ai1Select.value) ai1Select.value = newPath;
    else if (ai2Select && !ai2Select.value) ai2Select.value = newPath;

    if (resultArea) resultArea.textContent = `✅ クローン成功: ${teamName}`;
  } catch (err) {
    if (resultArea) resultArea.textContent = `❌ エラー: ${err.message}`;
  }
});

document.addEventListener("DOMContentLoaded", async () => {
  // Users 初期化（サーバ優先、失敗時は localStorage フォールバック）
  try {
    const users = await fetchUsers();
    clonedTeams.length = 0;
    users.forEach(u => clonedTeams.push({ id: u.id, name: u.name, path: u.path }));
  } catch (e) {
    console.warn("GET /users 失敗。localStorageにフォールバック:", e);
    const stored = localStorage.getItem("clonedTeams");
    if (stored) {
      try {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed)) clonedTeams.push(...parsed);
      } catch { }
    }
  } finally {
    updateAISelectors();
    renderTeamList();
  }

  // ゲームID復元 or 新規発行 → 盤面初期表示
  try {
    currentGameId = sessionStorage.getItem("game_id");
    if (currentGameId) {
      try {
        await getBoard(); // 有効ならそのまま表示
      } catch {
        currentGameId = null; // 404 等なら再発行へ
      }
    }
    if (!currentGameId) {
      await startNewGame();
      const init = await getBoard();
      setStatusText(`Player ${init.current_player}'s turn`);
    }
  } catch (e) {
    console.error("初期化失敗:", e);
  }
});

// ================== サイドバー ==================
const sidebar = document.getElementById("appSidebar");
const overlay = document.getElementById("sidebarOverlay");
const toggleBtn = document.getElementById("sidebarToggle");
const closeBtn = document.getElementById("sidebarClose");

function openSidebar() {
  if (!sidebar || !overlay || !toggleBtn) return;
  sidebar.classList.add("open");
  overlay.hidden = false;
  toggleBtn.setAttribute("aria-expanded", "true");
  sidebar.setAttribute("aria-hidden", "false");
}
function closeSidebar() {
  if (!sidebar || !overlay || !toggleBtn) return;
  sidebar.classList.remove("open");
  overlay.hidden = true;
  toggleBtn.setAttribute("aria-expanded", "false");
  sidebar.setAttribute("aria-hidden", "true");
}
toggleBtn?.addEventListener("click", () => {
  if (!sidebar) return;
  if (sidebar.classList.contains("open")) closeSidebar();
  else openSidebar();
});
closeBtn?.addEventListener("click", closeSidebar);
overlay?.addEventListener("click", closeSidebar);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && sidebar?.classList.contains("open")) closeSidebar();
});

// ================== 2戦目ボタン ==================
document.getElementById("nextMatchButton")?.addEventListener("click", async () => {
  const btn = document.getElementById("nextMatchButton");
  if (btn) btn.style.display = "none";

  // Auto状態とボタン表示を初期化
  isAutoRunning = false;
  isAutoPlaying = false;
  const autoBtn = document.getElementById("autoButton");
  if (autoBtn) {
    autoBtn.textContent = "オート開始";
    autoBtn.setAttribute("aria-pressed", "false");
    autoBtn.disabled = false;
  }

  try {
    // ① 旧ゲームを削除
    if (currentGameId) {
      await fetchJSON(`${BASE_URL}/games/${currentGameId}`, { method: "DELETE" });
      currentGameId = null;
      localStorage.removeItem("game_id");
    }

    // ② 新しいゲームを発行
    await startNewGame();
    const init = await fetchJSON(`${BASE_URL}/games/${currentGameId}`);

    // ③ 盤面とUIを完全初期化
    clearBoardVisual();
    updateBoardVisual(init.board);
    setStatusText(`2戦目開始！ Player ${init.current_player} の手番`);

    stopTimer(false);
    remainingTime = getSelectedTime();
    updateTimerDisplay();

    const log = document.getElementById("logMessages");
    if (log) {
      const p = document.createElement("p");
      p.textContent = "―――――― 🆕 2戦目開始 ――――――";
      log.appendChild(p);
      log.scrollTop = log.scrollHeight;
    }
  } catch (e) {
    setStatusText(`⚠️ 2戦目の初期化に失敗: ${e.message || e}`);
    alert(`⚠️ 2戦目の初期化に失敗: ${e.message || e}`);
  }
});

// ================== フォールバック自動手（タイムアップ時用） ==================
// === フォールバック自動手（タイムアップ時用） ===
async function autoMove() {
  const { epoch, gid } = _snapEpochAndGameId();
  const boardData = await getBoard();
  if (epoch !== _epoch || gid !== currentGameId) return;

  const board = boardData.board;
  for (let y = 0; y < 4; y++) {
    for (let x = 0; x < 4; x++) {
      for (let z = 0; z < 4; z++) {
        if (board[z][y][x] === 0) {
          await postMove(x, y); // postMove 側で再チェック済み
          return;
        }
      }
    }
  }
}

// ================== 新規ゲーム発行 ==================
async function startNewGame() {
  const data = await fetchJSON(`${BASE_URL}/games`, { method: 'POST' });
  console.log("📥 /games からのレスポンス:", data);
  currentGameId = data?.game_id || null;
  if (!currentGameId) throw new Error("game_idの取得に失敗しました");
  sessionStorage.setItem("game_id", currentGameId);
}

// ================== 盤面リセット（描画だけ） ==================
function clearBoardVisual() {
  for (const p of pieces) scene.remove(p);
  pieces = [];
  blinkingPieces = [];
}

// ================== Users 再同期（必要なら呼ぶ） ==================
async function refreshUsersFromServer() {
  const users = await fetchUsers();
  clonedTeams.length = 0;
  users.forEach(u => clonedTeams.push({ id: u.id, name: u.name, path: u.path }));
  updateAISelectors();
  renderTeamList();
}

function disablePlayButtons() {
  const stepBtn = document.getElementById("stepButton");
  const autoBtn = document.getElementById("autoButton");
  if (stepBtn) stepBtn.disabled = true;
  if (autoBtn) autoBtn.disabled = true;
}

function enablePlayButtons() {
  const stepBtn = document.getElementById("stepButton");
  const autoBtn = document.getElementById("autoButton");
  if (stepBtn) stepBtn.disabled = false;
  if (autoBtn) autoBtn.disabled = false;
}
