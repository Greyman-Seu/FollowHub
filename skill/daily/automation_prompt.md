Run the FollowHub daily production workflow for the sources enabled by the date strategy injected above: arXiv and RSS on weekdays, RSS only on Saturday and Sunday.

Requirements:

1. Read `skill/daily/SKILL.md` and every child skill it requires before acting.
2. On weekdays, run arXiv and RSS raw acquisition concurrently, then follow each production stage in order. On Saturday and Sunday, do not start any arXiv acquisition or paper workers; run only the RSS stages.
3. This scheduled run is unattended. Do not rely on collaboration-thread subagents. Use equivalent standalone worker delegation (for example, independent batch workers that write the same JSON result artifacts) for every paper/item-level prefilter, filter, translation, and organization-completion decision. Do not use `--auto-workers` or heuristic production output.
4. Publish completed results to R2. On weekdays, same-day publishing must preserve both arXiv and RSS sections. The current `follow-publish` implementation may not automatically merge the existing same-day remote digest, so explicitly merge the two completed local digests before the final publish when necessary. On Saturday and Sunday, publish the RSS digest with an arXiv count of zero and no arXiv items; an empty arXiv section emitted by the common digest schema is allowed.
5. Verify the actual remote JSON content, not only object existence:
   - `follow/latest.json`
   - `follow/daily/YYYY-MM-DD.json`
   - every affected `follow/sources/*.json`
6. Write the normal verification artifacts for every scheduled source. Weekdays require both arXiv and RSS verification; Saturday and Sunday require RSS verification only. Do not claim success until local and remote counts match for every scheduled source and the weekend arXiv count is zero.
7. Diagnose configured source-family outages honestly. By default, when every configured feed in a family fails acquisition, treat that family as unavailable and keep the run pending. If the scheduled runner explicitly marks a family optional for this installation, continue the remaining verified sources, publish them normally, and clearly report the outage in diagnostics and notification.
8. Preserve unrelated dirty-worktree changes. Do not publish fallback-quality Chinese text.

On a weekday, if the arXiv listing for the requested date is not available yet, leave the run pending. On any day, if a required worker, artifact, or verification remains incomplete, leave the run pending and exit without claiming success. The system timer will retry two hours later.
