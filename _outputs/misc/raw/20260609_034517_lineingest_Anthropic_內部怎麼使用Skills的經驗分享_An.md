---
title: "Anthropic 內部怎麼使用Skills的經驗分享，An"
type: raw
status: draft
date: 2026-06-09
updated: 2026-06-09
ingested_at: "2026-06-09 03:45:17 (UTC+8)"
ingest_source: line
ingest_extractor: gemini-2.5-flash-lite
category: other
source_tier: 
confidence: low
tags: []
reviewer: 待指派
---

# Anthropic 內部怎麼使用Skills的經驗分享，An

**分類**：other (其他)

> [!summary]
> (萃取失敗，僅保留原文)

## 原文

```
Anthropic 內部怎麼使用Skills的經驗分享，Anthropic 內部大量使用 Claude Code 的 skills，目前有上百個在活躍使用中。這篇文章是他們在用 skills 加速開發的過程中學到的經驗。這篇6/3部落格的文章是整理之前的文章後再提煉的，可以當作一些最佳做法的複習，也可以把整篇提供給agent做skill的優化
Skills 已經成為 最常被使用的擴充點之一。它們很靈活、容易製作、容易複製和提供他人使用。也可以跨不同的平台或不同agent使用。
但這種靈活性也讓人很難知道什麼做法最有效。什麼類型的 skills 值得做？怎麼組織一個 skill 的結構？什麼時候該把它分享給別人？所以這篇文章有蠻完整針對這些內容的目前最佳做法
━━━━━━━━━━━━━━━━━━━━
▍Skills 是什麼
Skills 是由指令、腳本和資源組成的資料夾，agent 可以發現並使用它們來更準確、更高效地做事。這篇文章假設你已經熟悉 skills 的基礎知識，如果你是新手，可以從 Anthropic 在 Skilljar 上的「Introduction to agent skills」課程開始。
一個常見的誤解是 skills「只是 markdown 檔案」。它們其實是資料夾，可以包含腳本、assets、資料等等，agent 可以發現、探索和操作這些內容。
在 Claude Code 裡，skills 還有大量的設定選項，包括註冊動態 hooks。Anthropic 發現最有效的 skills 就是那些善用這些設定選項和資料夾結構的。
━━━━━━━━━━━━━━━━━━━━
▍九種 Skill 類型
Anthropic 把內部所有 skills 做了一次盤點，發現它們聚集成九個類別。最好的 skills 乾淨地落在一個類別裡；那些試圖做太多事情的 skills 橫跨好幾個類別，反而讓 agent 困惑。這不是一份最終清單，但它是一個有用的框架，可以辨識你自己的 skills 庫裡有什麼缺口。
▍1. Library 和 API 參考
解釋怎麼正確使用某個 library、CLI 或 SDK。可以是內部 library 也可以是 Claude Code 有時候會搞錯的常用 library。這類 skills 通常包含一個參考程式碼片段的資料夾和一份 Claude 應該避免的 gotchas 清單。
範例：billing-lib（你的內部計費 library 的邊界情況和雷區）、internal-platform-cli（內部 CLI wrapper 的每個子指令和使用範例）、sandbox-proxy（設定你組織的 egress gateway，包括哪些 host 可達、怎麼 debug「connection refused」、怎麼加白名單）。
▍2. 產品驗證（Product verification）
描述怎麼測試或驗證你的程式碼是否正常運作。通常搭配 Playwright、tmux 或其他外部工具做驗證。驗證 skills 在 Anthropic 內部對 Claude 輸出品質的可量測影響最大。讓一個工程師花一週的時間專門做好你的驗證 skills 是值得的。可以考慮讓 Claude 錄一段影片展示它測試的輸出，這樣你可以看到它到底測了什麼；或者在每一步強制做程式化的狀態斷言。
範例：signup-flow-driver（在 headless browser 裡跑完註冊 → email 驗證 → onboarding，每一步可以做狀態斷言）、checkout-verifier（用 Stripe 測試卡跑結帳 UI，驗證發票確實落在正確的狀態）、tmux-cli-driver（需要 TTY 的互動式 CLI 測試）。
▍3. 資料抓取和分析（Data fetching and analysis）
連接到你的資料和監控堆疊。可能包含帶有 credentials 的資料抓取 library、特定的 dashboard ID，以及常見工作流程或取得資料方式的說明。
範例：funnel-query（「要 join 哪些 events 才能看到 signup → activation → paid」加上有正確 user_id 的表）、cohort-compare（比較兩個群組的留存或轉換，標示統計顯著的差異）、grafana（datasource UID、cluster 名稱、問題 → dashboard 對照表）、datadog（欄位參考、service 清單、metric 前綴慣例）。
▍4. 業務流程和團隊自動化（Business process and team automation）
把重複的工作流程自動化成一個指令。通常是比較簡單的指令但可能有更複雜的對其他 skills 或 MCP 的依賴。把先前的結果存在 log 檔案裡可以幫助模型保持一致性並反思之前的執行。
範例：standup-post（彙整你的 ticket tracker、GitHub 活動和之前的 Slack → 格式化的 standup，只顯示差異）、create-ticket（強制 schema 包括合法的 enum 值和必填欄位，加上建立後的工作流程如 ping reviewer、在 Slack 裡放連結）、weekly-recap（merged PR + closed tickets + deploys → 格式化的週回顧）。
▍5. 程式碼 scaffolding 和模板
為程式碼庫裡的特定功能生成框架 boilerplate。可能搭配可組合的腳本。在你的 scaffolding 有自然語言需求、無法純粹用程式碼覆蓋的時候特別有用。
範例：new-framework-workflow（用你的 annotations scaffold 一個新的 service/workflow/handler）、new-migration（你的 migration 檔案模板加上常見 gotchas）、create-app（新的內部 app 已預接好你的 auth、logging 和 deploy 設定）。
▍6. 程式碼品質和 review
在你的組織內強制程式碼品質並幫助 review 程式碼。可以包含確定性的腳本或工具來最大化穩健性。你可能想把這些 skills 自動執行，作為 hooks 或 GitHub Action 的一部分。
範例：adversarial-review（生成一個全新視角的子 agent 來批評，實作修正，迭代直到發現降級為挑剔級別）、code-style（強制程式碼風格，特別是 Claude 預設做不好的風格）、testing-practices（怎麼寫測試和測試什麼的說明）。
▍7. CI/CD 和部署
幫你在程式碼庫裡 fetch、push 和 deploy 程式碼。可能引用其他 skills 來收集資料。
範例：babysit-pr（監控一個 PR → 重試 flaky CI → 解決 merge conflicts → 啟用 auto-merge）、deploy-service（build → smoke test → 漸進流量切換同時比較 error rate → error 上升自動回滾）、cherry-pick-prod（隔離 worktree → cherry-pick → 衝突解決 → 用模板開 PR）。
▍8. Runbooks
接收一個症狀（比如 Slack thread、alert 或 error signature），走過一個多工具的調查流程，然後產出一份結構化報告。
範例：service-debugging（把症狀對應到工具和查詢模式，針對你流量最高的 service）、oncall-runner（抓取 alert → 檢查常見嫌疑犯 → 格式化發現）、log-correlator（給一個 request ID，從每個可能碰過它的系統裡拉出對應的 log）。
▍9. 基礎設施操作（Infrastructure operations）
執行例行維護和操作程序，其中一些涉及需要護欄的破壞性操作。讓工程師在關鍵操作中更容易遵循最佳實踐。
範例：resource-orphans（找到孤立的 pods/volumes → 貼到 Slack → 等待期 → 使用者確認 → 連鎖清理）、dependency-management（你組織的依賴審批工作流程）、cost-investigation（「為什麼我們的 storage/egress 帳單飆升了」加上特定的 bucket 和查詢模式）。
━━━━━━━━━━━━━━━━━━━━
▍製作 Skills 的技巧
決定了要做什麼 skill 之後，怎麼寫它？以下是 Claude Code 團隊的最佳實踐、技巧和訣竅。
▍不要說顯而易見的事
Claude 已經會寫程式了，而且可以讀你的程式碼庫。一個只是重述 Claude 預設就會做的事情的 skill 增加了 context 但沒有增加價值。如果你發布的 skill 主要是關於知識，那就專注在那些會把 Claude 推出它正常思考方式的資訊。
frontend design skill 是一個很好的例子。它是 Anthropic 的一個工程師透過跟客戶反覆迭代來改善 Claude 的設計品味而建的，避開經典的模式，像是 Inter 字體和紫色漸層。
▍建一個 Gotchas 區段
任何 skill 裡最高信號的內容就是 Gotchas 區段。這些區段應該從 Claude 在使用你的 skill 時碰到的常見失敗點逐漸累積起來。理想上你會隨時間更新你的 skill 來捕捉這些 gotchas。
範例：「subscriptions 表是 append-only 的。你要的那一行是 version 最高的那行，不是 created_at 最近的。」「這個欄位在 API gateway 裡叫 @request_id，在 billing service 裡叫 trace_id。它們是同一個值。」「Staging 即使 Stripe webhook 沒有真正處理也會回傳 200。去看 payment_events 才有真正的狀態。」
▍用檔案系統和漸進揭露
skill 是一個資料夾，不只是一個 markdown 檔案。你應該把整個檔案系統當作一種 context engineering 和漸進揭露的形式。告訴 Claude 你的 skill 裡有什麼檔案，它會在適當的時候讀它們。
最簡單的漸進揭露形式是指向其他 markdown 檔案讓 Claude 使用。比如你可以把詳細的函數簽名和使用範例拆到 references/api.md。
另一個例子：如果你的最終輸出是一個 markdown 檔案，你可以在 assets/ 裡放一個模板檔案讓它複製使用。
你可以有 references、scripts、examples 等等的資料夾，幫助 Claude 更有效地工作。
▍避免強行鎖定 Claude
Claude 通常會試圖遵循你的指令，而且因為 skills 是可重複使用的，你要小心不要在指令裡太過具體。給 Claude 它需要的資訊，但給它適應情況的彈性。
▍想清楚設定流程
有些 skills 可能需要使用者提供一些 context 來做設定。比如你做了一個把 standup 貼到 Slack 的 skill，你可能需要 Claude 問使用者要貼到哪個 Slack 頻道。
一個好的做法是把這些設定資訊存在 skill 目錄裡的 config.json 檔案。如果 config 沒有設定好，agent 就可以問使用者要資訊。
如果你希望 agent 呈現結構化的多選題，你可以指示 Claude 使用 AskUserQuestion 工具。
▍Description 是寫給模型看的，不是寫給人看的
當 Claude Code 啟動一個 session 時，它會建一份所有可用 skills 和 description 的清單。Claude 掃描這份清單來決定「這個請求有沒有對應的 skill？」。這代表 description 欄位不是摘要，它是一份描述什麼時候應該觸發這個 skill 的說明。
在 description 裡加入觸發詞會很有幫助。
▍幫 Claude 記住
有些 skills 可以透過在裡面儲存資料來實現一種記憶形式。你可以用任何東西來存資料，從簡單的 append-only 文字 log 檔案或 JSON 檔案，到複雜的 SQLite 資料庫。
比如一個 standup-post skill 可以保留一個 standups.log，記錄它寫過的每一篇 standup。下次你跑它的時候，Claude 讀自己的歷史，就能知道從昨天到現在什麼改變了。
你可以用環境變數 ${CLAUDE_PLUGIN_DATA} 來取得一個穩定的目錄來存資料。更多關於在 skills 裡持久化資料的說明可以參考官方文件：https://code.claude.com/docs/en/plugins-reference......
▍存放腳本和生成程式碼
你能給 Claude 的最強大工具之一就是程式碼。給 Claude 腳本和 library，讓 Claude 把它的回合花在組合上（決定下一步做什麼），而不是重建 boilerplate。
比如在你的 data-science skill 裡，你可能有一組從 event source 抓資料的 helper 函數。為了讓 Claude 做複雜分析，你給它一組這樣的 helper 函數，然後 Claude 可以即時生成腳本來組合這些功能，回應像「週二發生了什麼？」這樣的 prompt。
▍使用 on-demand hooks
Skills 可以包含只在 skill 被呼叫時才啟動的 hooks，而且只在 session 期間有效。把這個用在那些你不想一直跑、但有時候非常有用的、比較有意見的 hooks 上。
範例：/careful（透過 PreToolUse matcher 在 Bash 上阻止 rm -rf、DROP TABLE、force-push、kubectl delete。你只在碰 prod 的時候才想要這個，一直開會讓你瘋掉。）/freeze（阻止任何不在特定目錄裡的 Edit/Write。debug 的時候很有用：「我想加 log 但我一直不小心在『修』不相關的程式碼。」）
━━━━━━━━━━━━━━━━━━━━
▍分發 Skills
Skills 最大的好處之一是你可以分享給團隊其他人。
兩種分享方式：把 skills check in 到你的 repo 裡（在 ./.claude/skills 下面），或做成 plugin 放到 Claude Code Plugin marketplace 讓使用者上傳和安裝。
對比較小的團隊在少數幾個 repo 裡工作的情況，check in 到 repo 裡 work 得很好。但每一個被 check in 的 skill 也會對模型的 context 增加一點點。隨著 scale 變大，內部 plugin marketplace 讓你可以分發 skills、讓你的團隊決定安裝哪些，同時包含一個設定流程。
━━━━━━━━━━━━━━━━━━━━
▍管理 Skills Marketplace
怎麼決定哪些 skills 進 marketplace？怎麼讓人提交？
在 Anthropic，他們沒有一個集中的團隊來決定。他們試圖有機地找到最有用的 skills。如果有人有一個 skill 想讓大家試用，他們可以上傳到 GitHub 的 sandbox 資料夾，然後在 Slack 或其他論壇裡指給大家看。
一旦一個 skill 獲得了足夠的牽引力（由 skill owner 自己判斷），他們可以開一個 PR 把它移進 marketplace。
━━━━━━━━━━━━━━━━━━━━
▍組合 Skills
你可能想要 skills 之間有依賴關係。比如你可能有一個上傳檔案的 skill 和一個生成 CSV 並上傳的 skill。這種依賴管理目前還沒有原生地內建在 marketplace 或 skills 裡面，但你可以直接用名稱引用其他 skills，只要它們有被安裝，模型就會呼叫它們。
━━━━━━━━━━━━━━━━━━━━
▍量測 Skills
為了理解一個 skill 的表現，Anthropic 使用一個 PreToolUse hook 來記錄公司內部的 skill 使用情況。這代表他們可以找到受歡迎的 skills 或觸發率低於預期的 skills。
━━━━━━━━━━━━━━━━━━━━
▍怎麼開始
Skills 的最佳實踐還在演進中。Anthropic 最好的 skills 大部分都是從幾行文字和一個 gotcha 開始的，然後因為人們在 Claude 碰到新的邊界情況時不斷添加而變得更好。
理解 skills 最好的方式就是開始做、實驗、看什麼對你有效。
相關資源：Skills 官方文件（https://code.claude.com/docs/en/skills）、可客製化的範例 skills（https://github.com/anthropics/skills）。
```

## 抓取的網頁/影片資訊

- ❌ https://code.claude.com/docs/en/plugins-reference...... — HTTP Error 404: Not Found
- ❌ https://code.claude.com/docs/en/skills）、可客製化的範例 — 'ascii' codec can't encode characters in position 19-27: ordinal not in range(128)
- ❌ https://github.com/anthropics/skills）。 — 'ascii' codec can't encode characters in position 22-23: ordinal not in range(128)
