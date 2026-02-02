
import React from 'react';
import { LightningSplit } from './ui/lightning-split';
import { Zap, Clock, UserX, Target, Rocket, MousePointer2, FastForward } from 'lucide-react';

const NitroSide = () => (
  <div className="h-full w-full bg-slate-950 flex flex-col items-center justify-center p-12 text-center relative overflow-hidden">
    {/* Efeito de Profundidade */}
    <div className="absolute top-0 left-0 w-full h-full opacity-30 pointer-events-none">
       <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-blue-600 rounded-full blur-[160px]" />
       <div className="absolute bottom-1/4 right-1/4 w-64 h-64 bg-cyan-500 rounded-full blur-[120px]" />
    </div>
    
    <div className="relative z-10 flex flex-col items-center">
      {/* Logotipo Centralizado da Seção - Novo Padrão */}
      <div className="relative mb-8 group">
        <div className="absolute -inset-6 bg-[#00B4FF] rounded-[40px] blur-3xl opacity-30 group-hover:opacity-60 transition-opacity animate-pulse" />
        <div className="relative bg-gradient-to-br from-[#47C1FF] to-[#0055FF] p-10 rounded-[38px] shadow-2xl shadow-blue-500/50 flex items-center justify-center border border-white/20">
          <Zap className="w-24 h-24 text-white fill-white drop-shadow-[0_0_15px_rgba(255,255,255,0.8)]" />
        </div>
        {/* Badge de Versão/Status */}
        <div className="absolute -bottom-2 -right-2 bg-white text-[#0055FF] px-4 py-1.5 rounded-xl text-[10px] font-black uppercase italic tracking-tighter border border-blue-200 shadow-xl">
          v3.1 High-Speed
        </div>
      </div>

      <div className="flex flex-col items-center gap-2">
        <h2 className="text-6xl md:text-8xl font-[900] text-white tracking-tighter italic uppercase leading-none">
          A ERA DO <span className="nitro-text-gradient brightness-125">NITRO</span>
        </h2>
        <div className="h-1 w-24 bg-gradient-to-r from-transparent via-[#00B4FF] to-transparent rounded-full mb-2" />
        <p className="text-blue-300 text-xl font-bold uppercase tracking-[0.4em] italic drop-shadow-md">Fim da Busca Nominal</p>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-2xl text-left mt-12">
        <div className="bg-white/5 backdrop-blur-md border border-white/10 p-6 rounded-2xl flex items-center gap-4 hover:bg-white/10 transition-colors">
          <div className="bg-gradient-to-br from-[#47C1FF] to-[#0055FF] p-2.5 rounded-xl">
            <Zap className="w-8 h-8 text-white fill-white" />
          </div>
          <span className="text-white font-black italic uppercase text-sm leading-tight">Extração de Sócios <br/><span className="text-blue-400 text-[10px]">Em Lote Instantâneo</span></span>
        </div>
        <div className="bg-white/5 backdrop-blur-md border border-white/10 p-6 rounded-2xl flex items-center gap-4 hover:bg-white/10 transition-colors">
          <div className="bg-blue-600/20 p-2.5 rounded-xl border border-blue-500/30">
            <Target className="w-8 h-8 text-blue-400" />
          </div>
          <span className="text-white font-black italic uppercase text-sm leading-tight">Bypass de Secretária <br/><span className="text-blue-400 text-[10px]">Acesso Direto ao Dono</span></span>
        </div>
      </div>
    </div>
  </div>
);

const ManualSide = () => (
  <div className="h-full w-full bg-gray-100 flex flex-col items-center justify-center p-12 text-center">
    <div className="flex flex-col items-center">
      <div className="bg-gray-200 p-8 rounded-[32px] mb-8 border border-gray-300 shadow-inner">
        <Clock className="w-16 h-16 text-gray-400" />
      </div>
      <h2 className="text-6xl md:text-8xl font-[900] text-gray-400 tracking-tighter mb-4 italic uppercase leading-none">
        TRABALHO <span className="text-gray-300">BRAÇAL</span>
      </h2>
      <p className="text-gray-400 text-xl font-bold uppercase tracking-[0.3em] mb-12 italic">Escravidão Operacional</p>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-2xl text-left">
        <div className="bg-gray-200 border border-gray-300 p-6 rounded-2xl flex items-center gap-4 opacity-70">
          <MousePointer2 className="w-8 h-8 text-gray-400" />
          <span className="text-gray-500 font-black italic uppercase text-sm">Buscando Empresa <br/>por Empresa</span>
        </div>
        <div className="bg-gray-200 border border-gray-300 p-6 rounded-2xl flex items-center gap-4 opacity-70">
          <UserX className="w-8 h-8 text-gray-400" />
          <span className="text-gray-500 font-black italic uppercase text-sm">Barrado no <br/>"contato@"</span>
        </div>
      </div>
    </div>
  </div>
);

export const ComparisonLightning: React.FC = () => {
  return (
    <section className="bg-white">
      <LightningSplit 
        leftComponent={<NitroSide />} 
        rightComponent={<ManualSide />} 
      />
    </section>
  );
};
