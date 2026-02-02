
import React, { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';

export const FAQ: React.FC = () => {
  const faqs = [
    {
      q: "De onde vêm os dados?",
      a: "Coletamos informações de fontes públicas oficiais e registros empresariais consolidados, processando milhões de registros para encontrar o contato direto dos sócios."
    },
    {
      q: "Os contatos são atualizados?",
      a: "Nossa base é sincronizada mensalmente. Realizamos varreduras periódicas para garantir que as informações de quadro societário e contatos reflitam as mudanças mais recentes do mercado."
    },
    {
      q: "Como funciona o pagamento?",
      a: "O NitroLeads funciona exclusivamente através de um sistema de créditos por recarga. Você adquire a quantidade que precisa e usa quando quiser. Não existem planos, mensalidades ou contratos de fidelidade."
    }
  ];

  const [openIndex, setOpenIndex] = useState<number | null>(0);

  return (
    <section id="faq" className="py-20 bg-[#F8F9FA]">
      <div className="container mx-auto px-4 md:px-6">
        <div className="max-w-3xl mx-auto">
          <h2 className="text-3xl font-extrabold text-center text-[#212529] mb-12 uppercase italic tracking-tighter">Dúvidas Frequentes</h2>
          
          <div className="space-y-4">
            {faqs.map((faq, idx) => (
              <div 
                key={idx} 
                className="bg-white rounded-[12px] shadow-sm border border-gray-100 overflow-hidden"
              >
                <button 
                  className="w-full flex items-center justify-between p-6 text-left hover:bg-gray-50 transition-colors"
                  onClick={() => setOpenIndex(openIndex === idx ? null : idx)}
                >
                  <span className="font-bold text-[#212529]">{faq.q}</span>
                  {openIndex === idx ? <ChevronUp className="w-5 h-5 text-[#0D6EFD]" /> : <ChevronDown className="w-5 h-5 text-gray-400" />}
                </button>
                {openIndex === idx && (
                  <div className="p-6 pt-0 text-gray-500 text-sm leading-relaxed border-t border-gray-50">
                    {faq.a}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
};
