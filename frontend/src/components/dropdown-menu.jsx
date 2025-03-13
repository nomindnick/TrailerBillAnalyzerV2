// frontend/src/components/DownloadMenu.jsx

import React, { useState } from 'react';
import * as DropdownMenuPrimitive from '@radix-ui/react-dropdown-menu';
import { cn } from '@/lib/utils';
import { Download, FileText, FileIcon, Check, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useTheme } from '../lib/ThemeProvider';

const DropdownMenu = DropdownMenuPrimitive.Root;
const DropdownMenuTrigger = DropdownMenuPrimitive.Trigger;

const DropdownMenuContent = React.forwardRef(
  ({ className, sideOffset = 4, ...props }, ref) => (
    <DropdownMenuPrimitive.Portal>
      <DropdownMenuPrimitive.Content
        ref={ref}
        sideOffset={sideOffset}
        className={cn(
          'z-50 min-w-[12rem] overflow-hidden rounded-md border bg-white p-2 text-gray-950 shadow-lg animate-in ' +
            'data-[side=bottom]:slide-in-from-top-2 ' +
            'data-[side=left]:slide-in-from-right-2 ' +
            'data-[side=right]:slide-in-from-left-2 ' +
            'data-[side=top]:slide-in-from-bottom-2 ' +
            'dark:bg-gray-950 dark:text-gray-50 dark:border-gray-800',
          className
        )}
        {...props}
      />
    </DropdownMenuPrimitive.Portal>
  )
);
DropdownMenuContent.displayName = 'DropdownMenuContent';

const DropdownMenuItem = React.forwardRef(({ className, ...props }, ref) => (
  <DropdownMenuPrimitive.Item
    ref={ref}
    className={cn(
      'relative flex cursor-default select-none items-center rounded-sm px-3 py-2.5 text-sm outline-none ' +
        'focus:bg-gray-100 focus:text-gray-900 ' +
        'data-[disabled]:pointer-events-none data-[disabled]:opacity-50 ' +
        'dark:focus:bg-gray-800 dark:focus:text-gray-50',
      className
    )}
    {...props}
  />
));
DropdownMenuItem.displayName = 'DropdownMenuItem';

const DownloadMenu = ({ reportUrl }) => {
  const { theme } = useTheme();
  const [isDownloadingPdf, setIsDownloadingPdf] = useState(false);
  const [isViewingHtml, setIsViewingHtml] = useState(false);
  const [downloadComplete, setDownloadComplete] = useState(false);

  console.log('DownloadMenu rendering with reportUrl:', reportUrl);

  const handleViewHtml = () => {
    console.log('Opening HTML report:', reportUrl);
    setIsViewingHtml(true);
    window.open(reportUrl, '_blank');
    setTimeout(() => setIsViewingHtml(false), 1000);
  };

  const handleDownloadPdf = async () => {
    try {
      setIsDownloadingPdf(true);
      // Convert "…/filename.html" => "…/filename.pdf"
      const pdfUrl = `${reportUrl.split('.').slice(0, -1).join('.')}.pdf`;
      console.log('Downloading PDF from:', pdfUrl);

      const response = await fetch(pdfUrl);

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Failed to download PDF: ${errorText}`);
      }

      const contentType = response.headers.get('content-type');
      if (!contentType || !contentType.includes('application/pdf')) {
        throw new Error('Invalid PDF response from server');
      }

      const blob = await response.blob();
      const downloadUrl = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = 'bill_analysis.pdf';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(downloadUrl);

      // Show success indicator
      setDownloadComplete(true);
      setTimeout(() => setDownloadComplete(false), 2000);
    } catch (error) {
      console.error('Error downloading PDF:', error);
      alert(`Failed to download PDF: ${error.message}`);
    } finally {
      setIsDownloadingPdf(false);
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-lg shadow-md hover:shadow-lg transition-all">
          <Download size={20} />
          Download Report
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuItem onClick={handleViewHtml} disabled={isViewingHtml}>
          {isViewingHtml ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              <span>Opening...</span>
            </>
          ) : (
            <>
              <FileText className="mr-2 h-4 w-4" />
              <span>View HTML Report</span>
            </>
          )}
        </DropdownMenuItem>
        <DropdownMenuItem onClick={handleDownloadPdf} disabled={isDownloadingPdf || downloadComplete}>
          {downloadComplete ? (
            <>
              <Check className="mr-2 h-4 w-4 text-green-500" />
              <span className="text-green-500">Downloaded!</span>
            </>
          ) : isDownloadingPdf ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              <span>Downloading...</span>
            </>
          ) : (
            <>
              <FileIcon className="mr-2 h-4 w-4" />
              <span>Download PDF</span>
            </>
          )}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
};

export default DownloadMenu;