---
description: news.md の新しいお知らせを LP のお知らせ欄に反映する
disable-model-invocation: true
---

1. news.md を読み、index.html のお知らせ欄(id="news")を新しい順の 3 件にする
2. 日付は time 要素の datetime 属性にも入れる
3. news.md に無いことは書き足さない。CLAUDE.md の表現のルールを守る
4. python3 quality_check.py を実行し、結果を報告する