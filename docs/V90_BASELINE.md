# CoinCat v90.0 clean baseline — October 29, 2026

Baseline: 014a5ad1a786ce9a01680e3b8daa63c0e6f6f4f1 (coincat-v80).
The requested coincat_v80b remote branch was not returned by GitHub during preparation.
Application identity is v90.0. This baseline incorporates v80 Test Patch 01.

The urgent Experimental handoff now exports submitted_sizes,
preconsumer_rejected_sizes and preconsumer_rejections in the existing strict
consumer funnel. Each rejected size receives one first-failing upstream reason:
NOT_SINGLE_RESEARCH_ORDER, PRODUCT_NO_LONGER_APPROVED,
QUEUED_MODEL_INVENTORY_CHANGED, ROUTE_MARK_COVERAGE_INCOMPLETE,
MANUAL_BUDGET_UNAVAILABLE, or NO_CURRENT_RAM_FUNDING.
Counts describe repeated size reviews, not distinct opportunities or trades.
For an observed handoff, submitted sizes equal upstream/preconsumer rejections
plus reviewed sizes. An upstream rejection is not an economic loss and does not
increment consumer unpriced/negative counts. Session blockers and stopped-session
snapshots retain these explanations; re-arming starts fresh as before.

Test in a separate extracted source folder. Do not overlay a running installation
or copy private_data, private_backups or a vault. Run 02_SETUP_COINCAT.bat and
03_VERIFY_COINCAT.bat on Windows. No new permanent dataset is needed for verification.
If testing the normal UI separately, follow START_HERE.md's explicit fresh-data
confirmation and preserve your existing installation and backups.

Expected verification: 434 distinct offline tests, zero failures/errors/skips;
actual GUI and complete 18/18 diagnostic sections. Cloud validation is Linux
Python 3.11 only; native Windows/DPAPI and connected account behavior are untested.
A delayed candidate (>30 seconds) should now leave a nonzero upstream rejection
count rather than an unexplained empty consumer funnel. Stopped results stay visible.

Scope: this patch changes diagnostic accounting only. Existing decision guards,
LIVE block, fees, receipt calculation, financial files and manual ARM/STOP remain.
It does not repair alternative valuation-path selection, legacy-policy reporting,
or implement the proposed real-trade batch experiment. Those require separate
changes and adversarial valuation/execution/recovery tests. No exchange requests,
real orders, private financial data or credentials were used in patch validation.
