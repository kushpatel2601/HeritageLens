import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Highlighted } from "@/components/search/highlighted";

describe("<Highlighted>", () => {
  afterEach(cleanup);

  it("marks highlighted terms and shows ellipses for trimmed snippets", () => {
    const text = "the stepwell રાણકી વાવ at Patan";
    const start = text.indexOf("વાવ");
    const { container } = render(
      <Highlighted
        lang="gu"
        snippet={{ text, highlights: [[start, start + 3]], prefix_ellipsis: true, suffix_ellipsis: false }}
      />,
    );
    const p = container.querySelector("p")!;
    expect(p.getAttribute("lang")).toBe("gu");
    expect([...p.querySelectorAll("mark")].map((m) => m.textContent)).toEqual(["વાવ"]);
    expect(p.textContent).toBe(`… ${text}`);
  });

  it("renders plain text when the backend sends no highlights", () => {
    const { container } = render(
      <Highlighted snippet={{ text: "Rani ki Vav", prefix_ellipsis: false, suffix_ellipsis: true }} />,
    );
    expect(container.querySelectorAll("mark")).toHaveLength(0);
    expect(container.textContent).toBe("Rani ki Vav …");
  });
});
