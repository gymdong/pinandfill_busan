#!/usr/bin/env bash
# 열린 PR 과 지난 7일 병합 현황을 Discord 마크다운 텍스트로 표준출력에 낸다.
# 사용: GH_REPO=owner/repo ./weekly_summary.sh   (gh 로그인 또는 GH_TOKEN 필요)
set -euo pipefail

since=$(date -u -v-7d +%Y-%m-%d 2>/dev/null || date -u -d '7 days ago' +%Y-%m-%d)
stale_days=3

open=$(gh pr list --state open --limit 100 --json number,title,author,createdAt,updatedAt,isDraft,reviewDecision,baseRefName,url)
merged=$(gh pr list --state merged --limit 100 --search "merged:>=$since" --json number,title,author,url)

jq -rn --argjson open "$open" --argjson merged "$merged" --argjson stale "$stale_days" '
  def days(t): ((now - (t | fromdateiso8601)) / 86400 | floor);
  def line: "• [#\(.number) \(.title)](<\(.url)>) (@\(.author.login), \(days(.createdAt))일 전 생성, \(.reviewDecision | if . == "" or . == null then "리뷰 대기" else . end), → \(.baseRefName))";
  "**📋 주간 PR 현황**",
  "",
  "**열린 PR \($open | length)건**",
  ($open | sort_by(.createdAt) | map(select(.isDraft | not)) | if length == 0 then "없음" else map(line) | join("\n") end),
  "",
  "**⏳ \($stale)일 넘게 갱신 없는 PR**",
  ($open | map(select(days(.updatedAt) >= $stale)) | if length == 0 then "없음" else map(line) | join("\n") end),
  "",
  "**✅ 지난 7일 병합 \($merged | length)건**",
  ($merged | if length == 0 then "없음" else map("• [#\(.number) \(.title)](<\(.url)>) (@\(.author.login))") | join("\n") end)
'
