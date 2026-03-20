"use client";

import { useRef, useCallback } from "react";
import dynamic from "next/dynamic";
import { Code2 } from "lucide-react";

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), { ssr: false });

interface Props {
  code: string;
  onChange: (code: string) => void;
  onSave: () => void;
}

export default function CodeEditor({ code, onChange, onSave }: Props) {
  const editorRef = useRef<any>(null);

  const handleMount = useCallback((editor: any) => {
    editorRef.current = editor;
    // Ctrl+S to save
    editor.addCommand(2097 /* KeyMod.CtrlCmd | KeyCode.KeyS */, () => {
      onSave();
    });
  }, [onSave]);

  return (
    <div className="flex flex-col h-full">
      <div className="p-3 border-b border-zinc-800 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Code2 size={14} className="text-zinc-500" />
          <h2 className="text-sm font-semibold text-zinc-300">Strategy Code</h2>
        </div>
        <button onClick={onSave} className="btn-secondary">
          Save
        </button>
      </div>
      <div className="flex-1 min-h-0">
        {code ? (
          <MonacoEditor
            height="100%"
            language="python"
            theme="vs-dark"
            value={code}
            onChange={(val) => onChange(val || "")}
            onMount={handleMount}
            options={{
              minimap: { enabled: false },
              fontSize: 13,
              lineNumbers: "on",
              scrollBeyondLastLine: false,
              wordWrap: "on",
              tabSize: 4,
              padding: { top: 8 },
              renderLineHighlight: "none",
              overviewRulerBorder: false,
              hideCursorInOverviewRuler: true,
            }}
          />
        ) : (
          <div className="flex items-center justify-center h-full text-zinc-600 text-sm">
            <div className="text-center space-y-2">
              <Code2 size={32} className="mx-auto text-zinc-700" />
              <p>AI-generated code will appear here</p>
              <p className="text-xs text-zinc-700">You can also edit it manually</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
