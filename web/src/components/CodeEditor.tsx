import { json } from "@codemirror/lang-json";
import { markdown } from "@codemirror/lang-markdown";
import { githubDark } from "@uiw/codemirror-theme-github";
import CodeMirror from "@uiw/react-codemirror";

export function CodeEditor({
  value,
  onChange,
  language = "markdown",
  height = "320px",
  readOnly = false,
}: {
  value: string;
  onChange?: (v: string) => void;
  language?: "markdown" | "json";
  height?: string;
  readOnly?: boolean;
}) {
  return (
    <div className="overflow-hidden rounded-md border border-input">
      <CodeMirror
        value={value}
        height={height}
        readOnly={readOnly}
        theme={githubDark}
        extensions={language === "json" ? [json()] : [markdown()]}
        onChange={onChange}
        basicSetup={{ lineNumbers: true, foldGutter: false }}
      />
    </div>
  );
}
