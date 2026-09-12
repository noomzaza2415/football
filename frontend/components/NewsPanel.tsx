import { Panel } from "@/components/ui";
import type { NewsFeed } from "@/lib/types";

// Headlines from public RSS feeds, as reading context.
//
// Deliberately visually separated from the model output and captioned as such.
// Nothing here is an input to the analysis, and the panel says so, because a
// number sitting next to a headline invites the reader to assume otherwise.

function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "เมื่อครู่นี้";
  if (minutes < 60) return `${minutes} นาทีที่แล้ว`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} ชั่วโมงที่แล้ว`;
  return `${Math.round(hours / 24)} วันที่แล้ว`;
}

export default function NewsPanel({
  feed,
  title = "ข่าวบอลล่าสุด",
  description = "จาก RSS ของสำนักข่าวทั้งไทยและต่างประเทศ",
  emptyMessage = "ยังดึงข่าวไม่ได้ในขณะนี้",
}: {
  feed: NewsFeed | null;
  title?: string;
  description?: string;
  emptyMessage?: string;
}) {
  return (
    <Panel title={title} description={description}>
      <div className="mb-4 rounded-lg border border-warning/25 bg-warning/5 px-3 py-2">
        <p className="text-xs leading-relaxed text-ink-secondary">
          <span className="font-semibold text-ink">ข่าวไม่ได้เข้าไปในโมเดล</span>{" "}
          {feed?.note ??
            "พาดหัวข่าวเป็นข้อมูลประกอบการอ่านของคุณเท่านั้น ตัวเลขทั้งหมดในหน้านี้คำนวณจากผลการแข่งขันย้อนหลังล้วน ๆ"}
        </p>
      </div>

      {!feed || feed.items.length === 0 ? (
        <p className="py-4 text-sm text-ink-muted">{emptyMessage}</p>
      ) : (
        <ul className="space-y-3">
          {feed.items.map((item) => (
            <li key={item.url} className="border-b border-hairline/60 pb-3 last:border-0 last:pb-0">
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="group block focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-series-1"
              >
                <p className="text-sm font-medium leading-relaxed text-ink-secondary transition-colors group-hover:text-ink">
                  {item.title}
                </p>
                <p className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-ink-muted">
                  <span>{item.source}</span>
                  {item.language === "th" ? (
                    <span className="rounded bg-series-3/12 px-1.5 py-0.5 text-[10px] font-medium text-series-3">
                      ไทย
                    </span>
                  ) : (
                    <span className="rounded bg-series-1/12 px-1.5 py-0.5 text-[10px] font-medium text-series-1">
                      ต่างประเทศ
                    </span>
                  )}
                  {item.published_at ? <span>{timeAgo(item.published_at)}</span> : null}
                </p>
              </a>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
