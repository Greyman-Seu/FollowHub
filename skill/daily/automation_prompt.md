Run the FollowHub daily production workflow for both arXiv and RSS.

Requirements:

1. Read `skill/daily/SKILL.md` and every child skill it requires before acting.
2. Run arXiv and RSS raw acquisition concurrently, then follow each production stage in order.
3. This scheduled run is unattended. Do not rely on collaboration-thread subagents. Use equivalent standalone worker delegation (for example, independent batch workers that write the same JSON result artifacts) for every paper/item-level prefilter, filter, translation, and organization-completion decision. Do not use `--auto-workers` or heuristic production output.
4. Publish completed results to R2. Same-day publishing must preserve both arXiv and RSS sections. The current `follow-publish` implementation may not automatically merge the existing same-day remote digest, so explicitly merge the two completed local digests before the final publish when necessary.
5. Verify the actual remote JSON content, not only object existence:
   - `follow/latest.json`
   - `follow/daily/YYYY-MM-DD.json`
   - every affected `follow/sources/*.json`
6. Write the normal arXiv and RSS verification artifacts. Do not claim success until local and remote counts match for every source.
7. Diagnose configured source-family outages honestly. By default, when every configured feed in a family fails acquisition, treat that family as unavailable and keep the run pending. If the scheduled runner explicitly marks a family optional for this installation, continue the remaining verified sources, publish them normally, and clearly report the outage in diagnostics and notification.
8. Preserve unrelated dirty-worktree changes. Do not publish fallback-quality Chinese text.

If the arXiv listing for the requested date is not available yet, or any required worker/artifact/verification remains incomplete, leave the run pending and exit without claiming success. The system timer will retry two hours later.
