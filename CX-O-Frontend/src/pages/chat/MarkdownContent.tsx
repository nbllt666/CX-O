import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export function MarkdownContent({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      className="prose prose-sm max-w-none dark:prose-invert"
      components={{
        code({
          inline,
          className,
          children,
          ...props
        }: {
          inline?: boolean;
          className?: string;
          children?: React.ReactNode;
        }) {
          return !inline ? (
            <pre className="bg-[var(--color-bg-tertiary)] rounded-[var(--radius-md)] p-3 overflow-x-auto text-sm">
              <code className={className} {...props}>
                {children}
              </code>
            </pre>
          ) : (
            <code
              className="bg-[var(--color-bg-tertiary)] px-1.5 py-0.5 rounded text-sm"
              {...props}
            >
              {children}
            </code>
          );
        },
        table({ children }) {
          return (
            <div className="overflow-x-auto">
              <table className="min-w-full border-collapse border border-[var(--color-border)]">
                {children}
              </table>
            </div>
          );
        },
        th({ children }) {
          return (
            <th className="border border-[var(--color-border)] px-4 py-2 bg-[var(--color-bg-tertiary)] font-semibold">
              {children}
            </th>
          );
        },
        td({ children }) {
          return <td className="border border-[var(--color-border)] px-4 py-2">{children}</td>;
        },
      }}
    >
      {content}
    </ReactMarkdown>
  );
}
