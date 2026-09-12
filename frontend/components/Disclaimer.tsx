// The disclaimer required on every page. Two variants: a full banner for the
// top of a page, and a compact footnote for inside a card.

export function DisclaimerBanner({ text }: { text?: string }) {
  return (
    <aside
      role="note"
      className="panel flex items-start gap-3 border-warning/25 bg-warning/5 px-4 py-3"
    >
      <span aria-hidden="true" className="mt-1 text-base leading-none text-warning">
        ⚠
      </span>
      <p className="text-sm leading-relaxed text-ink-secondary">
        <span className="font-semibold text-ink">
          เครื่องมือวิเคราะห์สถิติเพื่อการศึกษาเท่านั้น
        </span>{" "}
        {text ??
          "ตัวเลขทั้งหมดเป็นค่าประมาณจากโมเดล ไม่ใช่การทำนายผลการแข่งขัน และไม่ได้การันตีผลใด ๆ การนำไปใช้พนันด้วยเงินจริงมีความเสี่ยงทางการเงิน คุณอาจสูญเสียเงินทั้งหมด ข้อมูลในเว็บนี้ไม่ใช่คำแนะนำทางการเงิน"}
      </p>
    </aside>
  );
}

export function DisclaimerFootnote({ className = "" }: { className?: string }) {
  return (
    <p className={`text-xs leading-relaxed text-ink-muted ${className}`}>
      ค่าประมาณจากโมเดล ใช้เพื่อการศึกษาเท่านั้น ไม่การันตีผลใด ๆ
      และการนำไปพนันมีความเสี่ยงที่จะสูญเสียเงินจริง
    </p>
  );
}
