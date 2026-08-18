import { Fragment, type ReactNode } from "react";

type MarkdownContentProps = {
  content: string;
};

export function MarkdownContent({ content }: MarkdownContentProps) {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];

    if (line.trim() === "") {
      index += 1;
      continue;
    }

    if (isTableStart(lines, index)) {
      const header = splitTableRow(line);
      const rows: string[][] = [];
      index += 2;

      while (index < lines.length && isTableRow(lines[index])) {
        rows.push(splitTableRow(lines[index]));
        index += 1;
      }

      blocks.push(
        <div
          aria-label="Itinerary details"
          className="markdownTableWrap"
          key={`table-${index}`}
          role="region"
          tabIndex={0}
        >
          <table>
            <thead>
              <tr>
                {header.map((cell, cellIndex) => (
                  <th key={`heading-${cellIndex}`}>{renderInline(cell)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={`row-${rowIndex}`}>
                  {header.map((_, cellIndex) => (
                    <td key={`cell-${rowIndex}-${cellIndex}`}>
                      {renderTableCell(row[cellIndex] ?? "")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }

    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading) {
      const level = Math.min(heading[1].length, 4);
      const HeadingTag = `h${level}` as "h1" | "h2" | "h3" | "h4";
      blocks.push(
        <HeadingTag key={`heading-${index}`}>
          {renderInline(heading[2])}
        </HeadingTag>,
      );
      index += 1;
      continue;
    }

    if (isListItem(line)) {
      const items: string[] = [];
      while (index < lines.length && isListItem(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*]\s+/, ""));
        index += 1;
      }
      blocks.push(
        <ul key={`list-${index}`}>
          {items.map((item, itemIndex) => (
            <li key={`item-${itemIndex}`}>{renderInline(item)}</li>
          ))}
        </ul>,
      );
      continue;
    }

    const paragraphLines: string[] = [];
    while (
      index < lines.length &&
      lines[index].trim() !== "" &&
      !isTableStart(lines, index) &&
      !/^(#{1,6})\s+/.test(lines[index]) &&
      !isListItem(lines[index])
    ) {
      paragraphLines.push(lines[index]);
      index += 1;
    }

    blocks.push(
      <p key={`paragraph-${index}`}>
        {paragraphLines.map((paragraphLine, lineIndex) => (
          <Fragment key={`line-${lineIndex}`}>
            {lineIndex > 0 ? <br /> : null}
            {renderInline(paragraphLine)}
          </Fragment>
        ))}
      </p>,
    );
  }

  return <div className="messageBody">{blocks}</div>;
}

function isListItem(line: string): boolean {
  return /^\s*[-*]\s+/.test(line);
}

function isTableRow(line: string): boolean {
  const trimmed = line.trim();
  return trimmed.startsWith("|") && trimmed.endsWith("|");
}

function isTableStart(lines: string[], index: number): boolean {
  if (!isTableRow(lines[index]) || index + 1 >= lines.length) {
    return false;
  }

  const separatorCells = splitTableRow(lines[index + 1]);
  return (
    separatorCells.length > 0 &&
    separatorCells.every((cell) => /^:?-{3,}:?$/.test(cell.replace(/\s/g, "")))
  );
}

function splitTableRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function renderTableCell(cell: string): ReactNode {
  const parts = cell.split(/<br\s*\/?>/gi);

  return parts.map((part, index) => (
    <div className={part.trim().startsWith("•") ? "tableBullet" : undefined} key={index}>
      {renderInline(part.replace(/^\s*•\s*/, ""))}
    </div>
  ));
}

function renderInline(text: string): ReactNode[] {
  const tokens = text.split(/(\*\*.+?\*\*|`.+?`|\*[^*\n]+\*)/g);

  return tokens.filter(Boolean).map((token, index) => {
    if (token.startsWith("**") && token.endsWith("**")) {
      return <strong key={index}>{token.slice(2, -2)}</strong>;
    }

    if (token.startsWith("`") && token.endsWith("`")) {
      return <code key={index}>{token.slice(1, -1)}</code>;
    }

    if (token.startsWith("*") && token.endsWith("*")) {
      return <em key={index}>{token.slice(1, -1)}</em>;
    }

    return token;
  });
}
