// src/components/ui/button.jsx
import React from 'react';
import { cn } from '@/lib/utils';

const buttonVariants = {
  variant: {
    default: 'bg-blue-600 text-white hover:bg-blue-700',
    destructive: 'bg-red-600 text-white hover:bg-red-700',
    outline: 'border border-gray-300 dark:border-gray-600 bg-transparent hover:bg-gray-100 dark:hover:bg-gray-800',
    secondary: 'bg-gray-200 text-gray-900 hover:bg-gray-300 dark:bg-gray-700 dark:text-gray-100 dark:hover:bg-gray-600',
    ghost: 'bg-transparent hover:bg-gray-100 dark:hover:bg-gray-800',
    link: 'bg-transparent text-blue-600 dark:text-blue-400 hover:underline'
  },
  size: {
    default: 'h-10 py-2 px-4',
    sm: 'h-8 px-3 text-sm',
    lg: 'h-12 px-6 text-lg',
    icon: 'h-10 w-10'
  }
};

export const Button = React.forwardRef(
  ({ className, variant = 'default', size = 'default', asChild = false, ...props }, ref) => {
    // Common classes for all variants
    const baseClasses = 'inline-flex items-center justify-center rounded-md font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 dark:focus:ring-offset-gray-900 disabled:opacity-50 disabled:pointer-events-none';

    // Generate class list based on variant and size
    const classes = cn(
      baseClasses,
      buttonVariants.variant[variant],
      buttonVariants.size[size],
      className
    );

    // If asChild is true, we should render props.children with our props
    if (asChild) {
      // Clone the child element and merge our props
      return React.cloneElement(React.Children.only(props.children), {
        className: classes,
        ref,
        ...props
      });
    }

    return (
      <button
        className={classes}
        ref={ref}
        {...props}
      />
    );
  }
);

Button.displayName = 'Button';