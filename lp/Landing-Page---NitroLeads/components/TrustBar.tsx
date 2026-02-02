
import React from 'react';
import { ShieldCheck, RefreshCw, Database } from 'lucide-react';

export const TrustBar: React.FC = () => {
  const trusts = [
    { icon: <ShieldCheck className="w-5 h-5" />, text: "Selo de Segurança SSL" },
    { icon: <RefreshCw className="w-5 h-5" />, text: "Base Sincronizada Mensalmente" },
    { icon: <Database className="w-5 h-5" />, text: "Dados Públicos Oficiais" },
  ];

  return (
    <div className="bg-[#F8F9FA] border-y border-gray-100 py-8">
      <div className="container mx-auto px-4">
        <div className="flex flex-col md:flex-row items-center justify-center gap-8 md:gap-16">
          <p className="text-sm font-bold text-gray-400 uppercase tracking-widest text-center">
            Inteligência de dados para prospecção de alta performance
          </p>
          <div className="flex flex-wrap justify-center items-center gap-6 md:gap-10">
            {trusts.map((item, idx) => (
              <div key={idx} className="flex items-center gap-2 text-gray-600 font-semibold text-sm">
                <span className="text-[#0D6EFD]">{item.icon}</span>
                <span>{item.text}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
