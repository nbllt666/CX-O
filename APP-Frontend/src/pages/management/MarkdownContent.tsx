/**
 * Markdown 渲染（对齐 CX-O-Frontend MarkdownContent，Task 8 功能增强 #1）
 *
 * - react-markdown + remark-gfm 渲染 assistant 正文（用户消息保持纯文本，由 ChatPage 区分）
 * - 代码块 / 表格 / 链接安全：链接仅放行 http(s)/mailto，拦截 javascript: 等危险协议
 * - 视觉沿用页面 --glass-* / --color-* token 与 Tailwind 语义色，不引入新的 prose 插件
 * - CSS 无 @tailwindcss/typography，故对常见块级元素做显式排版覆盖以保持可读性
 */
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';

const components: Components = {
  a({ href, children, ...props }) {
    // 链接安全：仅放行 http/https/mailto，其余协议一律退化为纯文本节点
    const safe = href && /^(https?:|mailto:)/i.test(href);
    if (!safe) {
      return <span {...props}>{children}</span>;
    }
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-accent underline-offset-2 hover:underline"
        {...props}
      >
        {children}
      </a>
    );
  },
  code({ className, children, ...props }) {
    const text = Array.isArray(children) ? children.join('') : String(children ?? '');
    // 行内代码 vs 代码块：带 language- 前缀（fenced + language）或含换行（fenced 无 language）
    const isBlock = Boolean(className?.includes('language-')) || text.includes('\n');
    if (isBlock) {
      return (
        <code className={className} {...props}>
          {children}
        </code>
      );
    }
    return (
      <code
        className="rounded bg-[rgba(255,255,255,0.08)] px-1.5 py-0.5 font-mono text-[0.85em]"
        {...props}
      >
        {children}
      </code>
    );
  },
  pre({ children }) {
    return (
      <pre className="my-2 overflow-x-auto rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.05)] p-3 text-xs">
        {children}
      </pre>
    );
  },
  h1({ children }) {
    return <h1 className="text-base font-semibold">{children}</h1>;
  },
  h2({ children }) {
    return <h2 className="text-base font-semibold">{children}</h2>;
  },
  h3({ children }) {
    return <h3 className="text-sm font-semibold">{children}</h3>;
  },
  h4({ children }) {
    return <h4 className="text-sm font-semibold">{children}</h4>;
  },
  h5({ children }) {
    return <h5 className="text-sm font-semibold">{children}</h5>;
  },
  h6({ children }) {
    return <h6 className="text-sm font-semibold">{children}</h6>;
  },
  ul({ children }) {
    return <ul className="list-disc space-y-1 pl-5">{children}</ul>;
  },
  ol({ children }) {
    return <ol className="list-decimal space-y-1 pl-5">{children}</ol>;
  },
  blockquote({ children }) {
    return (
      <blockquote className="border-l-2 border-accent/40 pl-3 text-muted-foreground">
        {children}
      </blockquote>
    );
  },
  table({ children }) {
    return (
      <div className="my-2 overflow-x-auto">
        <table className="w-full border-collapse text-xs">{children}</table>
      </div>
    );
  },
  th({ children }) {
    return (
      <th className="border border-[var(--glass-border)] bg-[rgba(255,255,255,0.05)] px-3 py-1.5 text-left font-medium">
        {children}
      </th>
    );
  },
  td({ children }) {
    return <td className="border border-[var(--glass-border)] px-3 py-1.5">{children}</td>;
  },
  hr() {
    return <hr className="border-[var(--glass-border)]" />;
  },
};

export function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="space-y-2 text-sm leading-relaxed">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}