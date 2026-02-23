'use client';

import { useState, type ReactNode } from 'react';
import { Sidebar } from './sidebar';
import { Header } from './header';
import { cn } from '@/lib/utils';

export function AppShell({ children }: { children: ReactNode }) {
    const [isSidebarOpen, setIsSidebarOpen] = useState(true);

    return (
        <div className="flex h-screen">
            {/* Collapsible nav sidebar */}
            <div
                className={cn(
                    'shrink-0 h-full transition-all duration-300 ease-in-out overflow-hidden',
                    isSidebarOpen ? 'w-64' : 'w-0'
                )}
            >
                <div className="w-64 h-full">
                    <Sidebar />
                </div>
            </div>

            {/* Main content area */}
            <div className="flex flex-1 flex-col overflow-hidden min-w-0">
                <Header
                    isSidebarOpen={isSidebarOpen}
                    onToggleSidebar={() => setIsSidebarOpen((prev) => !prev)}
                />
                <main className="flex-1 overflow-hidden">
                    {children}
                </main>
            </div>
        </div>
    );
}
