
import React from 'react';
import { UserCheck, PhoneCall, Map, Briefcase, Database, Download, Target, ChevronRight } from 'lucide-react';

export const Features: React.FC = () => {
  const features = [
    {
      icon: <UserCheck className="w-7 h-7" />,
      title: "Decisores Reais",
      desc: "Vá direto no Quadro Societário. Nome, cargo e participação de quem assina o contrato."
    },
    {
      icon: <PhoneCall className="w-7 h-7" />,
      title: "WhatsApp Validado",
      desc: "Telefones diretos dos sócios, sem filtros ou bloqueios da recepção."
    },
    {
      icon: <Map className="w-7 h-7" />,
      title: "Raio X Regional",
      desc: "Filtre por Estado e Cidade para prospecção focada em sua região de atuação."
    },
    {
      icon: <Briefcase className="w-7 h-7" />,
      title: "CNAE Cirúrgico",
      desc: "Encontre empresas pelo ramo exato, de padarias a grandes indústrias."
    },
    {
      icon: <Database className="w-7 h-7" />,
      title: "Base Estruturada",
      desc: "Acesse CNPJ, Razão Social e Data de Abertura para qualificar o tempo de mercado."
    },
    {
      icon: <Download className="w-7 h-7" />,
      title: "Exportação Nitro",
      desc: "Listas em CSV ou Excel prontas para disparos de vendas e automações."
    }
  ];

  return (
    <section id="recursos" className="py-24 bg-white relative">
      {/* Background Decor */}
      <div className="absolute top-0 left-0 w-full h-24 bg-gradient-to-b from-[#F8F9FA] to-transparent opacity-50" />
      
      <div className="container mx-auto px-4 md:px-6 relative">
        <div className="flex flex-col lg:flex-row justify-between items-end mb-20 gap-8">
          <div className="max-w-2xl">
            <span className="text-[#0D6EFD] font-black uppercase tracking-[0.4em] text-xs mb-4 block italic">O que entregamos</span>
            <h2 className="text-4xl md:text-5xl lg:text-6xl font-[900] text-[#212529] tracking-tighter">
              Ferramentas de <span className="text-[#0D6EFD]">Elite Comercial</span>
            </h2>
          </div>
          <a 
            href="https://nitroleads.online"
            className="bg-gray-900 text-white px-8 py-4 rounded-xl font-black text-sm flex items-center gap-2 hover:bg-[#0D6EFD] transition-all shadow-xl hover:-translate-y-1 uppercase tracking-widest italic"
          >
            Acessar Agora <ChevronRight className="w-5 h-5" />
          </a>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
          {features.map((f, i) => (
            <div key={i} className="group p-10 rounded-[32px] bg-white hover:bg-[#F8F9FA] border border-gray-100 hover:border-[#0D6EFD]/30 transition-all duration-500 hover:shadow-2xl hover:shadow-blue-500/5 flex flex-col items-start">
              <div className="w-16 h-16 rounded-[22px] bg-blue-50 text-[#0D6EFD] flex items-center justify-center mb-8 shadow-inner group-hover:scale-110 group-hover:bg-[#0D6EFD] group-hover:text-white transition-all duration-300">
                {f.icon}
              </div>
              <h3 className="text-2xl font-black text-[#212529] mb-4 uppercase tracking-tighter italic">{f.title}</h3>
              <p className="text-gray-500 font-medium leading-relaxed text-lg">{f.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
};
