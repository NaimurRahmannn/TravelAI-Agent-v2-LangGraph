import { Lightbulb } from "lucide-react";

type PracticalNotesProps = {
  notes: string[];
};

export function PracticalNotes({ notes }: PracticalNotesProps) {
  if (notes.length === 0) {
    return null;
  }

  return (
    <section aria-labelledby="notes-heading" className="practicalNotes">
      <header className="sectionHeading">
        <span>
          <Lightbulb aria-hidden="true" size={18} />
        </span>
        <div>
          <p>Before you go</p>
          <h3 id="notes-heading">Practical notes</h3>
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
