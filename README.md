# recruit-factory（求人LP量産システム）

ありがとうグループの加盟店ごとに、業務委託の職人を募集するページを **`data.yml` 1枚から** 作る仕組みです。
手本はタスカルさんの求人LP。「面談で話すことを先に全部出す」型を、全店で同じ品質・同じ安全さで出せるようにしています。

- 見本ページ（架空の会社）：https://miumiumiu4.github.io/recruit-factory/sample/
- 設計：[design/DESIGN.md](design/DESIGN.md) ／ 手本の分析：[design/ANALYSIS.md](design/ANALYSIS.md) ／ 壁打ち記録：[design/REVIEW.md](design/REVIEW.md)

## 新しい会社のページを作る流れ
1. **ヒアリング**：[prompts/P1_hearing.md](prompts/P1_hearing.md) をAIに貼ってオーナーに質問 → `data.yml` の下書き
2. **生成・PR**：[prompts/P2_build_publish.md](prompts/P2_build_publish.md) を Claude Code に貼る
3. **検品**：[prompts/P3_review.md](prompts/P3_review.md)
4. **オーナー承認**：プレビューURLを送り、OKなら `status.owner_approved_on` を更新して `meta.noindex: false`

## 自動で守ってくれること（`generator/build.py`）
| 止める（公開しない） | 隠す（警告） |
|---|---|
| 必須項目の不足 | 確認日から60日を過ぎた単価・実績 |
| 雇用の言葉（給与・勤務・シフト・入社・手取り・面接・採用 など） | 確認から30日を過ぎた募集枠 |
| リース・業者紹介・紹介料があるのに特商法の確認記録がない | 根拠9項目がそろわない収入例 |
| 研修が契約より前 | 同意のない声 |
| 支払いが作業完了から60日超 | 地元の事実が3つ未満の地域版 |
| 他店の声を自店の声として載せる | オーナー承認から60日→停止モード（noindex） |

毎朝6時（日本時間）に全社を自動でビルドし直すので、放置された数字は自動で消えます。

## 手元で試す
```
pip install pyyaml
python3 generator/build.py                         # 全社
python3 generator/build.py --only sample           # 1社
BUILD_DATE=2027-02-10 python3 generator/build.py   # 日付を進めて停止モードを確認
```
`_site/` に出力されます（コミットしません）。

※ 法務の論点は弁護士確認前の整理です。最初の1社の前に、特商法の該当性と研修の時期を弁護士に確認してください。
