
import React from 'react';
import { 
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Download, FileText, FilePdf } from 'lucide-react';
import { Button } from "@/components/ui/button"
import { useTheme } from '../lib/ThemeProvider';

const DownloadMenu = ({ reportUrl }) => {
  const { theme } = useTheme();

  const handleViewHtml = () => {
    window.open(reportUrl, '_blank');
  };

  const handleDownloadPdf = async () => {
    try {
      const pdfUrl = reportUrl.replace('.html', '.pdf');
      const response = await fetch(pdfUrl);
      
      if (!response.ok) {
        throw new Error('Failed to download PDF');
      }

      const blob = await response.blob();
      const downloadUrl = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = 'bill_analysis.pdf';
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(downloadUrl);
    } catch (error) {
      console.error('Error downloading PDF:', error);
      alert('Failed to download PDF. Please try again.');
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="primary" className="flex items-center gap-2 px-6 py-3 bg-green-600 hover:bg-green-700 text-white rounded-lg shadow-lg">
          <Download size={20} />
          Download Report
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className={`${theme === 'dark' ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'} border rounded-md shadow-lg min-w-[200px] p-2 z-50`}>
        <DropdownMenuItem onClick={handleViewHtml} className={`flex items-center px-4 py-2 text-sm rounded-md ${theme === 'dark' ? 'hover:bg-gray-700 text-gray-200' : 'hover:bg-gray-100 text-gray-700'} cursor-pointer`}>
          <FileText className="mr-2 h-4 w-4" />
          <span>View HTML</span>
        </DropdownMenuItem>
        <DropdownMenuItem onClick={handleDownloadPdf} className={`flex items-center px-4 py-2 text-sm rounded-md ${theme === 'dark' ? 'hover:bg-gray-700 text-gray-200' : 'hover:bg-gray-100 text-gray-700'} cursor-pointer`}>
          <FilePdf className="mr-2 h-4 w-4" />
          <span>Download PDF</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
};

export default DownloadMenu;
