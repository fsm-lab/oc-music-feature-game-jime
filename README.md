# Open Campus Feature Game

短い音源カードを聞き比べ、候補カードを「似ている順」に並べ替えるWebアプリです。ブラウザ側はHTML/CSS/JavaScript、ログ保存はPython標準ライブラリだけで動く簡易HTTPサーバーで実装しています。

## Purpose

このリポジトリの共有目的は、オープンキャンパスで使った評価アプリの構成を再利用・確認できるようにすることです。

- 参加者向けUI: 音源カードの再生、並べ替え、スマホ対応、テスト/公開モード
- ログAPI: `/api/log` へのPOSTをJSONLで保存
- 端末登録: `/api/register-device` で識別用テキストと送信元IPを保存
- 集計: JSONLログから特徴量別の順位集計CSVを作成

参加者ログ、端末登録結果、PID、トンネルログ、WAVクリップ実体はGitHubに含めません。

## Included Files

| File | Role |
| --- | --- |
| `suite_public.html` | 公開モード入口 |
| `suite_test.html` | テストモード入口 |
| `suite.html` | 共通UI |
| `suite_app.js` | ラウンド抽選、ドラッグ/タッチ並べ替え、ログPOST |
| `suite.css` | レスポンシブUI |
| `register_device.html` | 端末登録ページ |
| `server.py` | このフォルダ直下で動かす簡易ログサーバー |
| `gabor_http_with_game_logs.py` | 既存研究サーバー配置向けログサーバー |
| `cards_2sec.js` | 2秒カード用の生成済みラウンドデータ |
| `build_feature_probe_rounds.py` | 67特徴量分析結果からカードデータとWAVクリップを生成 |
| `summarize_logs.py` | JSONLログ集計 |
| `config/access_control.example.json` | IP/CIDR制限の設定例 |

## Quick Start

Python 3.10以降を想定しています。追加パッケージは不要です。

```bash
python server.py --host 127.0.0.1 --port 18082
```

Open:

```text
http://127.0.0.1:18082/suite_public.html
http://127.0.0.1:18082/suite_test.html
http://127.0.0.1:18082/register_device.html
```

音源クリップはこのリポジトリに含めていません。`cards_2sec.js` は生成時の公開URLを参照するため、別環境で完全に再現する場合は `clips/` を生成し直してください。

## Generate Card Data

`build_feature_probe_rounds.py` は、固定2秒窓の特徴量分析結果と特徴量相関表を入力にして、ラウンドデータとWAVクリップを生成します。

```bash
export METHOD_SWEEP_DIR=/path/to/20260601_method_sweep
export FEATURE_CORRELATION_CSV=/path/to/feature_correlation_all_pairs_fixed_window_2p0.csv
export METHOD_SWEEP_WEB_BASE=http://example.test/20260601_method_sweep
export GAME_WEB_BASE=http://example.test/open-campus-feature-game
python build_feature_probe_rounds.py
```

出力:

```text
cards_2sec.js
feature_probe_rounds_summary.csv
FEATURE_PROBE_DATASET.md
clips/*.wav
```

## Logs

公開モードは `logs/events.jsonl`、テストモードは `logs/test_events.jsonl` に追記されます。ログ行には、参加者が並べた候補順、ラウンドID、特徴量名、端末登録情報、送信元IP由来の分類情報が入ります。

集計:

```bash
python summarize_logs.py --input logs/events.jsonl --out-dir logs/summary
```

## Access Control

`config/access_control.example.json` を参考に `access_control.json` を作ると、許可CIDRやログ分割の設定を変えられます。`access_control.json` は環境依存設定なのでGit管理しません。

## HTTPS Tunnel

Cloudflare Quick Tunnelを使う場合:

```bash
APP_DIR="$(pwd)" LOCAL_URL=http://127.0.0.1:18082 bash start_https_quick_tunnel.sh
bash status_https_quick_tunnel.sh
bash stop_https_quick_tunnel.sh
```

Quick Tunnel URLは一時URLです。停止や再起動で変わります。

## Privacy Notes

- 氏名、学校名、連絡先は入力させない前提です。
- HTTPアプリから通常MACアドレスは取得できません。
- GitHubには `logs/`, `registered_devices.json`, `access_control.json`, `clips/` を入れない設定にしています。

