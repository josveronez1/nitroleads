
'use client';

import * as React from 'react';
import { X } from 'lucide-react';
import { cn } from '../../lib/utils';
import { cva, type VariantProps } from 'class-variance-authority';
import { Button } from './button';

const bannerVariants = cva(
	'relative overflow-hidden rounded-none border-b shadow-md text-sm z-[100]',
	{
		variants: {
			variant: {
				default: 'bg-muted/40 border-muted/80',
				success:
					'bg-green-50 border-green-200 text-green-900 dark:bg-green-900/20 dark:border-green-800 dark:text-green-100',
				warning:
					'bg-amber-50 border-amber-200 text-amber-900 dark:bg-amber-900/20 dark:border-amber-800 dark:text-amber-100',
				info: 'bg-blue-50 border-blue-200 text-blue-900 dark:bg-blue-900/20 dark:border-blue-800 dark:text-blue-100',
				premium:
					'bg-gradient-to-r from-[#0D6EFD] to-[#0A58CA] border-blue-400 text-white',
				gradient:
					'bg-slate-50 border-slate-200 text-slate-900 dark:bg-slate-800 dark:border-slate-700 dark:text-slate-100',
			},
			size: {
				default: 'py-2 px-4',
				sm: 'text-xs py-1 px-2',
				lg: 'text-lg py-4 px-6',
			},
		},
		defaultVariants: {
			variant: 'default',
			size: 'default',
		},
	},
);

type BannerProps = React.ComponentProps<'div'> &
	VariantProps<typeof bannerVariants> & {
		// Content
		title: string;
		description?: string;

		// Icons and visuals
		icon?: React.ReactNode;
		showShade?: boolean;

		// Actions
		show?: boolean;
		onHide?: () => void;
		action?: React.ReactNode;
		closable?: boolean;

		// Behavior
		autoHide?: number; // milliseconds
	};

export function Banner({
	variant = 'default',
	size = 'default',
	title,
	description,
	icon,
	showShade = false,
	show,
	onHide,
	action,
	closable = false,
	className,
	autoHide,
	...props
}: BannerProps) {
	React.useEffect(() => {
		if (autoHide) {
			const timer = setTimeout(() => {
				onHide?.();
			}, autoHide);
			return () => clearTimeout(timer);
		}
	}, [autoHide, onHide]);

	if (!show) return null;

	return (
		<div
			className={cn(bannerVariants({ variant, size }), className)}
			role={variant === 'warning' || variant === 'default' ? 'alert' : 'status'}
			{...props}
		>
			{/* Shimmer effect */}
			{showShade && (
				<div className="absolute inset-0 -z-10 bg-gradient-to-r from-transparent via-white/10 to-transparent animate-[shimmer_2s_infinite]" />
			)}

			<div className="container mx-auto flex items-center justify-between gap-4">
				<div className="flex min-w-0 flex-1 items-center gap-3">
					{icon && <div className="flex-shrink-0">{icon}</div>}

					<div className="min-w-0 flex-1">
						<div className="flex flex-wrap items-center gap-2">
							<p className="truncate font-black uppercase italic tracking-tighter">{title}</p>
              {description && <p className="text-[11px] opacity-90 font-bold hidden sm:block">{description}</p>}
						</div>
					</div>
				</div>

				<div className="flex flex-shrink-0 items-center gap-2">
					{action && action}

					{closable && (
						<Button onClick={onHide} size="icon" variant="ghost" className="h-6 w-6 text-white hover:bg-white/10">
							<X className="h-4 w-4" />
						</Button>
					)}
				</div>
			</div>
		</div>
	);
}
