'use client';

import { usePathname } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react';

const pageTitles: Record<string, string> = {
  '/': 'Dashboard',
  '/connections': 'Database Connections',
  '/schema': 'Schema Browser',
  '/mdl': 'MDL Semantic Layer',
  '/chat': 'Interactive Chat',
  '/knowledge': 'Knowledge Base',
  '/logs': 'Execution Logs',
};

interface HeaderProps {
  isSidebarOpen?: boolean;
  onToggleSidebar?: () => void;
}

export function Header({ isSidebarOpen, onToggleSidebar }: HeaderProps) {
  const pathname = usePathname();

  const title = pageTitles[pathname] ||
    Object.entries(pageTitles).find(([path]) =>
      path !== '/' && pathname.startsWith(path)
    )?.[1] ||
    'KAI Admin';

  return (
    <header className="flex h-14 items-center gap-3 border-b bg-background/50 px-4 backdrop-blur-sm sticky top-0 z-10 transition-all">
      {onToggleSidebar && (
        <Button
          variant="ghost"
          size="icon"
          onClick={onToggleSidebar}
          className="h-8 w-8 shrink-0"
          aria-label={isSidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
        >
          {isSidebarOpen
            ? <PanelLeftClose className="h-4 w-4" />
            : <PanelLeftOpen className="h-4 w-4" />}
        </Button>
      )}
      <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
        <span className="hover:text-foreground transition-colors cursor-default">Admin</span>
        <span className="text-muted-foreground/40">/</span>
      </div>
      <h1 className="text-lg font-semibold tracking-tight text-foreground">{title}</h1>

      <div className="ml-auto flex items-center gap-2">
      </div>
    </header>
  );
}
