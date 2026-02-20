import React, { useState, useEffect } from 'react';
import { Zap, Search, MapPin, CheckCircle2, TrendingUp, Users } from 'lucide-react';
import { SparklesCore } from './ui/sparkles';
import { trackMetaLead } from '../lib/utils';

interface HeroProps {
  isBannerVisible?: boolean;
}

export const Hero: React.FC<HeroProps> = ({ isBannerVisible = false }) => {
  const [leadsCount, setLeadsCount] = useState(12480);

  useEffect(() => {
    const interval = setInterval(() => {
      setLeadsCount(prev => prev + Math.floor(Math.random() * 3));
    }, 4000);
    return () => clearInterval(interval);
  }, []);

  const paddingTopClass = isBannerVisible ? 'pt-44 lg:pt-56' : 'pt-32 lg:pt-48';

  return (
    <section className={`relative ${paddingTopClass} pb-16 lg:pb-24 overflow-hidden bg-white`}>
      <div className="absolute inset-0 z-0 pointer-events-none opacity-40">
        <SparklesCore
          id="tsparticleshero"
          background="transparent"
          minSize={0.6}
          maxSize={1.4}
          particleDensity={30}
          className="w-full h-full"
          particleColor="#0D6EFD"
          speed={0.5}
        />
      </div>

      <div className="absolute top-0 right-0 w-1/3 h-full bg-[#0D6EFD]/5 -skew-x-12 translate-x-16 -z-10" />
      
      <div className="container mx-auto px-4 md:px-6 relative z-10">
        <div className="flex flex-col lg:flex-row items-center gap-16">
          
          <div className="flex-1 text-center lg:text-left">
            <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-blue-50 border border-blue-100 text-[#0D6EFD] text-xs font-black uppercase tracking-widest mb-8 animate-fade-in">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-600"></span>
              </span>
              CHEGA DE LDR BRAÇAL: ESCALANDO PROSPECÇÃO AGORA
            </div>

            <div className="relative inline-block mb-8">
              <h1 className="text-4xl md:text-5xl lg:text-7xl font-[900] text-[#212529] leading-[1.1] tracking-tighter relative z-20">
                Pare de caçar decisores <br />
                <span className="strikethrough-custom font-bold">um por um</span>. <br />
                <span className="nitro-text-gradient">Receba o contato direto.</span>
              </h1>
            </div>

            <p className="text-xl md:text-2xl text-gray-600 mb-10 max-w-2xl mx-auto lg:mx-0 leading-relaxed font-medium">
              Elimine o trabalho de pesquisar empresa por empresa. O NitroLeads entrega o <span className="text-[#212529] font-bold border-b-2 border-[#0D6EFD]">WhatsApp e e-mail dos donos</span> em lote. 
              Escalável. Rápido. Fatal.
            </p>
            
            <div className="flex flex-col sm:flex-row items-center gap-6 justify-center lg:justify-start">
              <a 
                href="#cta"
                onClick={() => trackMetaLead('CTA_HERO_ATIVAR_NITRO')}
                className="nitro-gradient glow-button text-white px-10 py-6 rounded-[16px] font-black text-xl flex items-center gap-3 shadow-2xl shadow-blue-500/40 transition-all hover:-translate-y-2 active:scale-95 w-full sm:w-auto uppercase italic"
              >
                <Zap className="w-6 h-6 fill-current" />
                ATIVAR MODO NITRO
              </a>
              
              <div className="flex -space-x-3">
                {[1,2,3,4].map(i => (
                  <div key={i} className="w-10 h-10 rounded-full border-2 border-white bg-gray-200 flex items-center justify-center overflow-hidden">
                    <img src={`https://api.dicebear.com/7.x/avataaars/svg?seed=${i + 22}`} alt="User" />
                  </div>
                ))}
                <div className="flex flex-col pl-6 justify-center text-left">
                  <div className="flex items-center gap-1 text-yellow-500">
                    {[1,2,3,4,5].map(i => <Zap key={i} className="w-3 h-3 fill-current" />)}
                  </div>
                  <span className="text-[10px] font-bold text-gray-400 uppercase">Aprovado por quem odeia perder tempo</span>
                </div>
              </div>
            </div>
          </div>

          <div className="flex-1 w-full max-w-2xl relative">
            <div className="absolute -inset-4 bg-gradient-to-r from-blue-500 to-cyan-400 rounded-[24px] blur-2xl opacity-20 animate-pulse"></div>
            
            <div className="glass-card rounded-[24px] shadow-2xl border border-white/40 p-1 relative z-10 overflow-hidden">
              <div className="bg-white rounded-[22px] p-6 lg:p-8">
                <div className="flex items-center justify-between mb-8">
                  <div className="flex gap-2">
                    <div className="w-3 h-3 rounded-full bg-red-400 shadow-sm" />
                    <div className="w-3 h-3 rounded-full bg-yellow-400 shadow-sm" />
                    <div className="w-3 h-3 rounded-full bg-green-400 shadow-sm" />
                  </div>
                  <div className="flex items-center gap-2">
                    <TrendingUp className="w-4 h-4 text-green-500" />
                    <span className="text-[10px] font-black text-gray-300 tracking-widest uppercase">Nitro Extraction v3.1</span>
                  </div>
                </div>

                <div className="bg-gray-50 border border-gray-100 rounded-[16px] p-4 mb-8 flex flex-col md:flex-row gap-4">
                  <div className="flex-1 flex items-center gap-3 px-4 py-3 bg-white border border-gray-200 rounded-[12px] shadow-sm">
                    <Search className="w-5 h-5 text-[#0D6EFD]" />
                    <span className="text-sm font-bold text-gray-700 italic">Pesquisa em Massa: Ativada</span>
                  </div>
                  <div className="flex-1 flex items-center gap-3 px-4 py-3 bg-white border border-gray-200 rounded-[12px] shadow-sm">
                    <Users className="w-5 h-5 text-[#0D6EFD]" />
                    <span className="text-sm font-bold text-gray-700 italic">Contatos: Apenas Sócios</span>
                  </div>
                </div>

                <div className="bg-gradient-to-br from-gray-900 to-gray-800 rounded-[20px] p-6 text-white shadow-2xl relative overflow-hidden">
                   <div className="absolute top-0 right-0 p-4 opacity-10">
                      <div className="bg-gradient-to-br from-[#47C1FF] to-[#0055FF] p-6 rounded-[24px]">
                        <Zap className="w-20 h-20 text-white fill-white" />
                      </div>
                   </div>
                   
                   <div className="flex justify-between items-start mb-6">
                      <div>
                        <span className="text-[10px] font-black text-blue-400 uppercase tracking-tighter mb-1 block">Filtro de Decisão</span>
                        <h3 className="text-xl font-black">Smart Corp Brasil</h3>
                      </div>
                      <div className="px-3 py-1 bg-green-500/20 text-green-400 text-[10px] font-black rounded-full border border-green-500/30 flex items-center gap-1">
                        <span className="w-1.5 h-1.5 bg-green-500 rounded-full pulse-dot" />
                        ACESSO DIRETO
                      </div>
                   </div>

                   <div className="space-y-4 relative z-10">
                      <div className="flex items-center gap-4 bg-white/5 p-4 rounded-[14px] border border-white/10">
                        <div className="w-12 h-12 rounded-full bg-gradient-to-br from-[#47C1FF] to-[#0055FF] flex items-center justify-center font-black text-lg">RF</div>
                        <div>
                          <p className="text-xs font-bold text-gray-400 uppercase">Sócio Administrador</p>
                          <p className="text-lg font-black">Ricardo Fonseca</p>
                        </div>
                        <CheckCircle2 className="w-6 h-6 text-blue-400 ml-auto" />
                      </div>

                      <div className="grid grid-cols-2 gap-3">
                        <div className="bg-white/5 p-3 rounded-[12px] border border-white/5 text-[11px]">
                          <span className="text-gray-400 block mb-1">E-mail Corporativo</span>
                          <span className="font-mono text-blue-300">ricardo@smartcorp.com.br</span>
                        </div>
                        <div className="bg-white/5 p-3 rounded-[12px] border border-white/5 text-[11px]">
                          <span className="text-gray-400 block mb-1">WhatsApp Sócio</span>
                          <span className="font-mono text-blue-300">(11) 98221-XXXX</span>
                        </div>
                      </div>
                   </div>
                </div>
              </div>
            </div>
            
            <div className="absolute -bottom-6 -right-6 md:right-10 glass-card p-4 rounded-[16px] shadow-xl z-20 flex items-center gap-3 border border-[#0D6EFD]/20 animate-bounce transition-all duration-1000">
               <div className="bg-gradient-to-br from-[#47C1FF] to-[#0055FF] p-2 rounded-[10px]">
                  <Zap className="w-5 h-5 text-white fill-white" />
               </div>
               <div>
                  <p className="text-[10px] font-black text-gray-400 uppercase">Velocidade de LDR</p>
                  <p className="text-lg font-black text-[#0D6EFD]">100x Mais Rápido</p>
               </div>
            </div>
          </div>

        </div>
      </div>
    </section>
  );
};
