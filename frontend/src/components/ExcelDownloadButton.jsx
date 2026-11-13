import React, { useState } from 'react';
import { FiDownload } from 'react-icons/fi';
import axios from 'axios';
import toast from 'react-hot-toast';

export default function ExcelDownloadButton({ data, compact = false }) {
  const [loading, setLoading] = useState(false);

  const isUnsupported = Boolean(
    data?.validation_gate?.validation_status === 'UNSUPPORTED_MODEL' ||
    data?.model_suitability?.supported === false
  );
  const modelType = String(data?.company?.model_type || data?.dcf_result?.model_type || '');
  const isReit = Boolean(modelType === 'REIT_INVIT_AFFO' || data?.dcf_result?.is_reit);
  const isInsurance = Boolean(modelType.startsWith('INSURANCE_') || data?.dcf_result?.is_insurance);
  const isEquityModel = Boolean(
    data?.company?.is_financial ||
    isInsurance ||
    isReit ||
    data?.company?.is_equity_model ||
    modelType === 'CORPORATE_DDM' ||
    data?.dcf_result?.is_equity_model
  );

  const handleDownload = async () => {
    if (!data) return;
    
    setLoading(true);
    const toastId = toast.loading(
      isUnsupported
        ? 'Generating Unsupported Model Gate Notice workbook...'
        : isReit
        ? 'Generating REIT AFFO / Cap-Rate Excel workbook...'
        : isInsurance
        ? 'Generating Insurance Actuarial DDM Excel workbook...'
        : isEquityModel
        ? 'Generating DDM / FCFE Excel workbook...'
        : 'Generating FCFF DCF Excel workbook...'
    );
    
    try {
      const response = await axios.post('/api/export/excel', { analysis_data: data }, {
        responseType: 'blob'
      });
      
      const dateStr = new Date().toISOString().split('T')[0];
      const methodTag = isUnsupported
        ? 'Gate_Notice'
        : isReit
        ? 'REIT_AFFO'
        : isInsurance
        ? 'Insurance_DDM'
        : isEquityModel
        ? 'DDM_FCFE'
        : 'FCFF_DCF';
      const filename = `${data.company.ticker}_${methodTag}_Valuation_Model_${dateStr}.xlsx`;
      
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', filename);
      document.body.appendChild(link);
      link.click();
      
      link.parentNode.removeChild(link);
      const okLabel = isUnsupported ? 'Gate Notice' : isReit ? 'REIT AFFO' : isInsurance ? 'Insurance DDM' : isEquityModel ? 'DDM / FCFE' : 'FCFF DCF';
      toast.success(`${okLabel} Excel workbook downloaded`, { id: toastId });
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
      className={`inline-flex items-center justify-center gap-1.5 sm:gap-2.5 rounded-xl font-display text-xs sm:text-sm font-bold transition cursor-pointer ${
        compact ? 'px-2.5 sm:px-4 py-1.5 sm:py-2.5' : 'w-full px-5 py-3'
      } ${
        loading || !data
          ? 'bg-[#18202c]/60 text-[#a6b0c3]/40 cursor-not-allowed border border-[#f4eedf]/10'
          : 'bg-[#141b26] hover:bg-[#1f2937] text-[#f4eedf] hover:text-[#e3b23c] border border-[#f4eedf]/15 hover:border-[#e3b23c]/50 shadow-md'
      }`}
    >
      <FiDownload className="w-3.5 h-3.5 sm:w-4.5 sm:h-4.5 text-[#e3b23c] shrink-0" />
      {compact ? (
        <>
          <span className="sm:hidden">{loading ? '...' : 'Excel'}</span>
          <span className="hidden sm:inline">{loading ? 'Exporting...' : `Export ${isUnsupported ? 'Gate Notice' : isReit ? 'REIT' : isInsurance ? 'Insurer' : isEquityModel ? 'DDM' : 'FCFF'} Excel (.xlsx)`}</span>
        </>
      ) : (
        <span>{loading ? 'Exporting...' : `Export ${isUnsupported ? 'Gate Notice' : isReit ? 'REIT' : isInsurance ? 'Insurer' : isEquityModel ? 'DDM' : 'FCFF'} Excel (.xlsx)`}</span>
      )}
    </button>
  );
}
