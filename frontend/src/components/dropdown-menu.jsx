
import React from 'react';
import { 
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Download, FileText, FilePdf } from 'lucide-react';
import { Button } from "@/components/ui/button"

const DownloadMenu = ({ reportUrl }) => {
  const handleViewHtml = () => {
    window.open(reportUrl, '_blank');
  };

  const handleDownloadPdf = async () => {
    try {
      // Convert HTML URL to PDF URL
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
        <Button className="flex items-center gap-2 px-6 py-3 bg-green-600 hover:bg-green-700 text-white rounded-lg">
          <Download size={20} />
          Download Report
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={handleViewHtml} className="cursor-pointer">
          <FileText className="mr-2 h-4 w-4" />
          <span>View HTML</span>
        </DropdownMenuItem>
        <DropdownMenuItem onClick={handleDownloadPdf} className="cursor-pointer">
          <FilePdf className="mr-2 h-4 w-4" />
          <span>Download PDF</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
};

export default DownloadMenu;
