import React, { useState } from 'react';
import { FiDownload } from 'react-icons/fi';
import axios from 'axios';
import toast from 'react-hot-toast';

export default function ExcelDownloadButton({ data, compact = false }) {
  const [loading, setLoading] = useState(false);

  const handleDownload = async () => {
    if (!data) return;
    
    setLoading(true);
    const toastId = toast.loading('Generating institutional Excel workbook...');
    
    try {
      const response = await axios.post('/api/export/excel', { analysis_data: data }, {
        responseType: 'blob'
      });
      
      const dateStr = new Date().toISOString().split('T')[0];
      const filename = `${data.company.ticker}_Valuation_Model_${dateStr}.xlsx`;
      
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', filename);
      document.body.appendChild(link);
      link.click();
      
      link.parentNode.removeChild(link);
      toast.success('Excel workbook downloaded', { id: toastId });
    } catch (error) {
      console.error("Excel download failed", error);
      toast.error('Failed to generate Excel file.', { id: toastId });
    } finally {
      setLoading(false);
    }
  };

  return (
    <button
      type="button"
      onClick={handleDownload}
      disabled={loading || !data}
      className={`inline-flex items-center justify-center gap-2.5 rounded-xl font-display text-xs sm:text-sm font-bold transition cursor-pointer ${
        compact ? 'px-4 py-2 sm:py-2.5' : 'w-full px-5 py-3'
      } ${
        loading || !data
          ? 'bg-[#18202c]/60 text-[#a6b0c3]/40 cursor-not-allowed border border-[#f4eedf]/10'
          : 'bg-[#141b26] hover:bg-[#1f2937] text-[#f4eedf] hover:text-[#e3b23c] border border-[#f4eedf]/15 hover:border-[#e3b23c]/50 shadow-md'
      }`}
    >
      <FiDownload className="w-4 h-4 sm:w-4.5 sm:h-4.5 text-[#e3b23c] shrink-0" />
      <span>{loading ? 'Exporting...' : 'Export Excel (.xlsx)'}</span>
    </button>
  );
}
