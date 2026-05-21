/**
 * jmty-watcher の Slack 通知と同じタイミングで listing を Google Sheets に1行追加するための
 * Apps Script。下記スプシ内 Apps Script エディタにそのままコピペし、SHARED_TOKEN を
 * .env / GitHub Secrets の SHEETS_WEBHOOK_TOKEN と同じ値に書き換える。
 *
 * セットアップ手順は docs/google_sheets_setup.md を参照。
 */

// ============================================================================
// 設定
// ============================================================================
const SHEET_NAME = 'listings';
// .env / GitHub Secrets の SHEETS_WEBHOOK_TOKEN と一致させる。
// 推測されにくい長い文字列にすること（例: openssl rand -hex 24）
const SHARED_TOKEN = 'CHANGE_ME_SHARED_TOKEN';

const HEADERS = [
  '画像',
  '追加日時',
  'priority',
  'タイトル',
  '場所',
  '価格(円)',
  '推定相場(円)',
  '出品URL',
  '対応状況',
  '担当者',
  'メモ',
  'article_id',
];

const STATUS_OPTIONS = ['未対応', '対応中', '対応済', 'スルー'];
const IMAGE_COLUMN_WIDTH = 120;
const IMAGE_ROW_HEIGHT = 90;

// ============================================================================
// Webhook 受信
// ============================================================================
function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    if (!body || body.token !== SHARED_TOKEN) {
      return _json({ ok: false, error: 'unauthorized' });
    }

    const sheet = _ensureSheet();

    // article_id で重複チェック（再実行や手動再投入で多重登録しない）
    if (body.article_id) {
      const finder = sheet
        .getRange(2, _colIndex('article_id'), Math.max(sheet.getLastRow() - 1, 0), 1)
        .createTextFinder(String(body.article_id))
        .matchEntireCell(true);
      const hit = finder.findNext();
      if (hit) {
        return _json({ ok: true, row: hit.getRow(), deduped: true });
      }
    }

    const thumb = body.thumbnail_url || '';
    sheet.appendRow([
      thumb ? `=IMAGE("${thumb}")` : '',
      body.added_at || '',
      body.priority || '',
      body.title || '',
      body.location || '',
      body.price_yen != null ? body.price_yen : '',
      body.estimated_market_price_yen != null ? body.estimated_market_price_yen : '',
      body.url || '',
      '未対応',
      '',
      '',
      body.article_id || '',
    ]);

    const row = sheet.getLastRow();
    sheet.setRowHeight(row, IMAGE_ROW_HEIGHT);
    _applyStatusValidation(sheet, row);

    return _json({ ok: true, row: row });
  } catch (err) {
    return _json({ ok: false, error: String(err && err.stack || err) });
  }
}

// ============================================================================
// 動作確認用 GET（ブラウザで Web App URL を開いた時に出る）
// ============================================================================
function doGet() {
  return _json({ ok: true, message: 'jmty-watcher sheets webhook is alive' });
}

// ============================================================================
// 初期化: 1回だけ実行する関数。シートを作ってヘッダ+書式+ドロップダウンを設定。
// Apps Script エディタの関数選択ドロップダウンで `setupSheet` を選んで実行。
// ============================================================================
function setupSheet() {
  const sheet = _ensureSheet();

  // ヘッダ
  sheet.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]).setFontWeight('bold');
  sheet.setFrozenRows(1);
  sheet.getRange(1, 1, 1, HEADERS.length).setBackground('#f1f3f4');

  // 画像列の幅
  sheet.setColumnWidth(_colIndex('画像'), IMAGE_COLUMN_WIDTH);

  // URL列の幅
  sheet.setColumnWidth(_colIndex('出品URL'), 320);
  sheet.setColumnWidth(_colIndex('タイトル'), 300);
  sheet.setColumnWidth(_colIndex('メモ'), 280);

  // 対応状況列のドロップダウン（2行目以降全部）
  _applyStatusValidation(sheet, 2, 1000);

  // article_id 列を非表示
  const articleIdCol = _colIndex('article_id');
  sheet.hideColumns(articleIdCol);

  SpreadsheetApp.getActive().toast('Sheet setup complete: ' + SHEET_NAME, 'jmty-watcher');
}

// ============================================================================
// ヘルパー
// ============================================================================
function _ensureSheet() {
  const ss = SpreadsheetApp.getActive();
  let sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
  }
  return sheet;
}

function _colIndex(headerName) {
  const i = HEADERS.indexOf(headerName);
  if (i < 0) throw new Error('Unknown column: ' + headerName);
  return i + 1; // 1-based
}

function _applyStatusValidation(sheet, startRow, numRows) {
  const col = _colIndex('対応状況');
  const rows = numRows || 1;
  const rule = SpreadsheetApp.newDataValidation()
    .requireValueInList(STATUS_OPTIONS, true)
    .setAllowInvalid(false)
    .build();
  sheet.getRange(startRow, col, rows, 1).setDataValidation(rule);
}

function _json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(
    ContentService.MimeType.JSON
  );
}
