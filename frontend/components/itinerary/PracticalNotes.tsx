import { Lightbulb } from "lucide-react";

type PracticalNotesProps = {
  idPrefix: string;
  notes: string[];
};

export function PracticalNotes({ idPrefix, notes }: PracticalNotesProps) {
  if (notes.length === 0) {
    return null;
  }

  const headingId = `${idPrefix}-notes-heading`;

  return (
    <section aria-labelledby={headingId} className="practicalNotes">
      <header className="sectionHeading">
        <span>
          <Lightbulb aria-hidden="true" size={18} />
        </span>
        <div>
          <p>Before you go</p>
          <h3 id={headingId}>Practical notes</h3>
        </div>
      </header>
      <ul>
        {notes.map((note, index) => (
          <li key={`${note.slice(0, 32)}-${index}`}>{note}</li>
        ))}
      </ul>
    </section>
  );
}
