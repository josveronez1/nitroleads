
import React from 'react';
import { XCircle, CheckCircle, Zap, ShieldAlert, Rocket } from 'lucide-react';

export const Comparison: React.FC = () => {
  return (
    <section className="py-24 bg-[#0A58CA]/5 relative overflow-hidden">
      {/* Abstract circles */}
      <div className="absolute top-0 right-0 w-96 h-96 bg-blue-500/5 rounded-full blur-[100px] -mr-48 -mt-48" />
      <div className="absolute bottom-0 left-0 w-96 h-96 bg-cyan-500/5 rounded-full blur-[100px] -ml-48 -mb-48" />

      <div className="container mx-auto px-4 md:px-6 relative z-10">
        <div className="text-center mb-24">
          <h2 className="text-4xl md:text-5xl lg:text-7xl font-black text-[#212529] mb-6 tracking-tighter italic uppercase leading-none">
            Sua prospecção está no <span className="text-red-500 underline decoration-red-200 underline-offset-8">passado?</span>
          </h2>
          <p className="text-xl md:text-2xl text-gray-500 max-w-2xl mx-auto font-medium">
            Enquanto você tenta passar pela recepção, seu concorrente já está fechando com o dono.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 max-w-7xl mx-auto">
          {/* Jeito Errado */}
          <div className="relative group">
            <div className="absolute -top-4 -left-4 bg-red-100 text-red-600 px-6 py-2 rounded-full text-xs font-[900] z-10 shadow-lg border border-red-200 tracking-widest uppercase italic">OBSOLETO</div>
            <div className="bg-white/60 backdrop-blur-sm rounded-[40px] p-12 border-2 border-dashed border-gray-300 h-full opacity-60 group-hover:opacity-80 transition-opacity">
              <h3 className="text-3xl font-black text-gray-400 mb-10 flex items-center gap-4 italic uppercase">
                <ShieldAlert className="w-10 h-10" />
                O "Filtro" Antigo
              </h3>
              <ul className="space-y-8">
                {[
                  "Falar com secretárias que barram sua entrada.",
                  "Enviar e-mails para 'contato@' que caem no lixo.",
                  "Comprar listas frias e desatualizadas.",
                  "Ligar sem saber o nome do decisor real.",
                  "Perder 4 horas por dia apenas caçando leads."
                ].map((text, i) => (
                  <li key={i} className="flex items-start gap-5 text-gray-500 font-bold text-lg">
                     <XCircle className="w-6 h-6 text-red-300 flex-shrink-0 mt-0.5" />
                     <span className="line-through decoration-red-200">{text}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {/* Jeito Nitro */}
          <div className="relative group">
            <div className="absolute -inset-2 bg-gradient-to-r from-[#0D6EFD] via-blue-400 to-cyan-500 rounded-[44px] blur-xl opacity-20 group-hover:opacity-40 transition duration-1000 group-hover:duration-200"></div>
            <div className="absolute -top-4 -right-4 nitro-gradient text-white px-8 py-2 rounded-full text-xs font-[900] z-10 shadow-2xl italic tracking-widest uppercase">PADRÃO NITRO</div>
            <div className="relative bg-white rounded-[40px] p-12 border-2 border-[#0D6EFD] h-full shadow-2xl shadow-blue-500/10">
              <h3 className="text-3xl font-black text-[#212529] mb-10 flex items-center gap-4 italic uppercase">
                <Rocket className="w-10 h-10 text-[#0D6EFD]" />
                Alta Performance
              </h3>
              <ul className="space-y-8">
                {[
                  "Acesso direto ao WhatsApp do Sócio-Administrador.",
                  "Dados filtrados por CNAE e tempo de mercado.",
                  "E-mails profissionais validados instantaneamente.",
                  "Filtros geográficos por Estado e Cidade.",
                  "Exportação em 1 clique para CRM ou Excel."
                ].map((text, i) => (
                  <li key={i} className="flex items-start gap-5 text-[#212529] font-black text-lg group/item transition-all hover:translate-x-2">
                     <div className="bg-blue-600 p-1.5 rounded-full shadow-lg shadow-blue-200">
                        <Zap className="w-5 h-5 text-white fill-white" />
                     </div>
                     {text}
                  </li>
                ))}
              </ul>
              
              <div className="mt-12 pt-8 border-t border-gray-100 flex justify-between items-center">
                 <p className="text-xs font-black text-[#0D6EFD] uppercase tracking-[0.4em] italic">Vantagem Competitiva</p>
                 <Zap className="w-6 h-6 text-[#0D6EFD] fill-[#0D6EFD] animate-pulse" />
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};
