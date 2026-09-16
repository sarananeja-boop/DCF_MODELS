import React, { useState } from 'react';
import { FiDownload } from 'react-icons/fi';
import axios from 'axios';
import toast from 'react-hot-toast';

export default function ExcelDownloadButton({ data }) {
  const [loading, setLoading] = useState(false);

  const handleDownload = async () => {
    if (!data) return;
    
    setLoading(true);
    const toastId = toast.loading('Generating IB-formatted Excel model...');
    
    try {
      const response = await axios.post('/api/export/excel', { analysis_data: data }, {
        responseType: 'blob' // Important for file download
      });
      
      const dateStr = new Date().toISOString().split('T')[0];
      const filename = `${data.company.ticker}_Valuation_Model_${dateStr}.xlsx`;
      
      // Create blob link to download
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', filename);
      document.body.appendChild(link);
      link.click();
      
      // Clean up
      link.parentNode.removeChild(link);
      toast.success('Excel model downloaded successfully!', { id: toastId });
    } catch (error) {
      console.error("Excel download failed", error);
      toast.error('Failed to generate Excel file.', { id: toastId });
    } finally {
      setLoading(false);
    }
  };

  return (
    <button
      onClick={handleDownload}
      disabled={loading || !data}
      className={`w-full flex items-center justify-center gap-2 py-3 mt-4 rounded-md font-semibold transition ${
        loading || !data
          ? 'bg-zinc-800/80 text-gray-500 cursor-not-allowed'
          : 'bg-zinc-800 hover:bg-zinc-700 text-zinc-100 border border-zinc-700'
      }`}
    >
      {loading ? (
        <span className="flex items-center gap-2">
          <svg className="animate-spin h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          Exporting...
        </span>
      ) : (
        <>
          <FiDownload className="text-lg" />
          Export to Excel
        </>
      )}
    </button>
  );
}
