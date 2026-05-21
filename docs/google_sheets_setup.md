# Google Sheets 連携セットアップ

Slack 通知と同じタイミングで listing をスプシに1行追加し、対応状況を担当者が手動管理するための連携。

## アーキテクチャ

```
watcher (GitHub Actions)
  └─ SheetsNotifier.append_listing
        ↓  POST {token, article_id, priority, ...}
スプシ Apps Script doPost
  └─ appendRow + IMAGE(thumb) + ドロップダウン
```

Service Account や OAuth は使わず、Apps Script の Web App URL を Webhook として叩く。

---

## 1. Apps Script を貼る

1. 対象スプシを開く（例: <https://docs.google.com/spreadsheets/d/1yZe3Xtr5dPXpPYtUExKjumYeh01dcyZ6Rd0QvLFkmKg/edit>）
2. メニュー **拡張機能 → Apps Script** をクリック
3. 開いたエディタの既存コード（`function myFunction() {}`）を全部消す
4. このリポジトリの [`scripts/apps_script.gs`](../scripts/apps_script.gs) の中身を全部コピペ
5. ファイル上部の `SHARED_TOKEN` を、自分で決めた長いランダム文字列に書き換える:
   ```js
   const SHARED_TOKEN = 'r4nd0m-secret-string-here';
   ```
   生成例:
   ```bash
   openssl rand -hex 24
   ```
6. **保存**（💾 アイコンまたは ⌘S）

## 2. シート初期化

1. エディタ上部、関数選択ドロップダウンで **`setupSheet`** を選択
2. **実行** ボタンをクリック
3. 初回は権限承認が出る:
   - **権限を確認** → 自分のGoogleアカウントを選ぶ
   - "Google hasn't verified this app" 警告 → **Advanced** → **Go to ... (unsafe)**（自分が書いたコードなのでOK）
   - **Allow**
4. 実行完了後、スプシに戻ると `listings` シートが作られ、ヘッダ・ドロップダウン・列幅が整っているはず

## 3. Web App としてデプロイ

1. エディタ右上の **デプロイ** → **新しいデプロイ**
2. ⚙️ アイコン → **ウェブアプリ** を選択
3. 設定:
   - **説明**: `jmty-watcher webhook`（任意）
   - **次のユーザーとして実行**: **自分**
   - **アクセスできるユーザー**: **全員**（※ 認証はトークンで行う）
4. **デプロイ**
5. 表示された **Web app URL** をコピー（`https://script.google.com/macros/s/AKfyc.../exec` のような形式）

> ⚠️ 「アクセスできるユーザー: 全員」だが、`SHARED_TOKEN` でリクエスト検証するため部外者が書き込むことはできない。

## 4. 疎通確認

ブラウザで Web App URL を開く → `{"ok":true,"message":"jmty-watcher sheets webhook is alive"}` が表示されればOK。

## 5. 環境変数を登録

### ローカル `.env`

```env
SHEETS_WEBHOOK_URL=https://script.google.com/macros/s/AKfyc.../exec
SHEETS_WEBHOOK_TOKEN=r4nd0m-secret-string-here
```

### GitHub Actions

リポジトリ **Settings → Secrets and variables → Actions → New repository secret** で:

| Name | Value |
| --- | --- |
| `SHEETS_WEBHOOK_URL` | デプロイで得た URL |
| `SHEETS_WEBHOOK_TOKEN` | `SHARED_TOKEN` と同じ値 |

`.github/workflows/watcher.yml` の `env:` ブロックにもこの2つを追加する必要があるが、既に PR で対応済み。

## 6. 動作確認

```bash
# ローカル疎通: モックで1件流す
uv run python -c "
from watcher.models import Classification, Listing
from watcher.sheets_notifier import SheetsNotifier
from watcher.config import load_config

cfg = load_config()
with SheetsNotifier(cfg.sheets_webhook_url, cfg.sheets_webhook_token) as s:
    s.append_listing(
        listing=Listing(
            article_id='article-test-' + __import__('time').strftime('%H%M%S'),
            url='https://jmty.jp/test',
            title='テスト出品',
            price_yen=1000000,
            prefecture='千葉',
            city='柏',
            category_label=None,
            thumbnail_url='https://via.placeholder.com/120x90.png?text=test',
        ),
        classification=Classification(
            is_actual_trailer_house=True,
            seller_type='individual',
            trailer_category='trailer_house',
            estimated_market_price_yen=1500000,
            price_gap_ratio=-0.33,
            condition_grade='good',
            priority='B',
            concerns=[],
            sales_pitch_hook='',
            model_version='test',
        ),
    )
"
```

スプシに1行追加されればOK。

---

## トラブルシュート

| 症状 | 原因 | 対処 |
| --- | --- | --- |
| Web App URL を GET したら HTML が返る | デプロイ未完了 or 権限承認まだ | デプロイ手順をやり直し |
| `{"ok":false,"error":"unauthorized"}` | `SHARED_TOKEN` の値が watcher 側と一致していない | 両側を見直し |
| 行は追加されるが画像が出ない | thumbnail_url が空 or リダイレクト先で IMAGE 関数が解釈失敗 | Cell に `=IMAGE(url, 1)` のように mode 指定で再描画 |
| 何度同じ listing が来ても増えない | 重複防止が効いてる（仕様） | 同じ article_id は再 append しない |
| Apps Script を更新したのに反映されない | デプロイは初回のみ。コード変更は「デプロイの管理 → ✏️ → 新しいバージョン」で再デプロイが必要 | 再デプロイ |
