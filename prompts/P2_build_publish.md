# P2 生成・公開プロンプト（Claude Code に1社分のページを作らせる）

> 使い方：Claude Code でこのリポジトリを開き、下の「---」から下を貼ります。`<slug>` と添付データを差し替えてください。

---

recruit-factory リポジトリで、加盟店 `<slug>` の求人ページを作って公開まで進めてください。

1. `sites/sample/` をコピーして `sites/<slug>/` を作り、添付のヒアリング結果（P1の出力）で `data.yml` を埋める
   - 事実がない項目は空欄のまま。作文で埋めない
   - 写真は `sites/<slug>/images/` に入れ、横1200px以下・1枚300KB以下にする
   - `meta.sample` は削除、`meta.noindex` は最初は `true`（会社の確認が終わるまで検索に出さない）
2. `python3 generator/build.py --only <slug>` を実行し、✖（エラー）が0になるまで data.yml を直す
   - ✖ が「特商法」「研修が契約の前」の場合は、data.yml を書き換えて消さず、本部代表に報告して止まる
   - －（隠した項目）は一覧にして報告する
3. `prompts/P3_review.md` の検品を、生成された `_site/<slug>/index.html` に対して行う
4. ブランチを切ってコミットし、PRを作る。PRの説明に、隠した項目・検品結果・オーナーへの宿題を書く
5. マージ後、`https://miumiumiu4.github.io/recruit-factory/<slug>/` をオーナーに送って確認してもらう
6. オーナーの「OK」が来たら `status.owner_approved_on` を今日にし、`meta.noindex` を `false` にして再度PR
