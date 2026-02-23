from django.core.management.base import BaseCommand
from lead_extractor.models import NormalizedNiche, NormalizedLocation


class Command(BaseCommand):
    help = 'Popula dados iniciais de nichos e localizações normalizadas. Para todas as cidades do Brasil (IBGE), use: python manage.py load_brazil_cities'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Populando nichos normalizados...'))
        
        # Lista de nichos comuns
        niches = [
            'Advogado', 'Médico', 'Dentista', 'Contador', 'Arquiteto', 'Engenheiro',
            'Veterinário', 'Psicólogo', 'Fisioterapeuta', 'Nutricionista', 'Personal Trainer',
            'Educador Físico', 'Farmacêutico', 'Enfermeiro', 'Fonoaudiólogo', 'Terapeuta Ocupacional',
            'Designer', 'Fotógrafo', 'Jornalista', 'Publicitário', 'Marketing Digital',
            'Desenvolvedor', 'Programador', 'Analista de Sistemas', 'Consultor', 'Coach',
            'Eletricista', 'Encanador', 'Pedreiro', 'Pintor', 'Marceneiro',
            'Mecânico', 'Funileiro', 'Borracharia', 'Lavagem de Carros', 'Auto Peças',
            'Restaurante', 'Lanchonete', 'Pizzaria', 'Padaria', 'Confeitaria',
            'Supermercado', 'Farmácia', 'Loja de Roupas', 'Loja de Calçados', 'Pet Shop',
            'Escola', 'Creche', 'Curso', 'Faculdade', 'Academia',
            'Hotel', 'Pousada', 'Salão de Beleza', 'Barbearia', 'Clínica de Estética',
            'Oficina', 'Ateliê', 'Estúdio', 'Clínica', 'Consultório',
        ]
        
        for niche_name in niches:
            normalized_name = niche_name.lower().strip()
            niche, created = NormalizedNiche.objects.get_or_create(
                name=normalized_name,
                defaults={
                    'display_name': niche_name,
                    'is_active': True
                }
            )
            if created:
                self.stdout.write(f'  ✓ Criado: {niche.display_name}')
            else:
                self.stdout.write(f'  - Já existe: {niche.display_name}')
        
        self.stdout.write(self.style.SUCCESS('\nPopulando localizações (cidades)...'))
        
        # Lista de cidades principais (capitais e principais cidades)
        cities = [
            # São Paulo
            ('São Paulo', 'SP'), ('Campinas', 'SP'), ('Guarulhos', 'SP'), ('São Bernardo do Campo', 'SP'),
            ('Santo André', 'SP'), ('Osasco', 'SP'), ('Sorocaba', 'SP'), ('Ribeirão Preto', 'SP'),
            ('Santos', 'SP'), ('Mauá', 'SP'), ('Diadema', 'SP'), ('Carapicuíba', 'SP'),
            ('Mogi das Cruzes', 'SP'), ('Piracicaba', 'SP'), ('Jundiaí', 'SP'), ('Bauru', 'SP'),
            
            # Rio de Janeiro
            ('Rio de Janeiro', 'RJ'), ('São Gonçalo', 'RJ'), ('Duque de Caxias', 'RJ'), ('Nova Iguaçu', 'RJ'),
            ('Niterói', 'RJ'), ('Campos dos Goytacazes', 'RJ'), ('Belford Roxo', 'RJ'), ('São João de Meriti', 'RJ'),
            
            # Minas Gerais
            ('Belo Horizonte', 'MG'), ('Uberlândia', 'MG'), ('Contagem', 'MG'), ('Juiz de Fora', 'MG'),
            ('Betim', 'MG'), ('Montes Claros', 'MG'), ('Ribeirão das Neves', 'MG'), ('Uberaba', 'MG'),
            
            # Rio Grande do Sul
            ('Porto Alegre', 'RS'), ('Caxias do Sul', 'RS'), ('Pelotas', 'RS'), ('Canoas', 'RS'),
            ('Santa Maria', 'RS'), ('Gravataí', 'RS'), ('Viamão', 'RS'), ('Novo Hamburgo', 'RS'),
            
            # Paraná
            ('Curitiba', 'PR'), ('Londrina', 'PR'), ('Maringá', 'PR'), ('Ponta Grossa', 'PR'),
            ('Cascavel', 'PR'), ('São José dos Pinhais', 'PR'), ('Foz do Iguaçu', 'PR'), ('Colombo', 'PR'),
            
            # Bahia
            ('Salvador', 'BA'), ('Feira de Santana', 'BA'), ('Vitória da Conquista', 'BA'), ('Camaçari', 'BA'),
            ('Juazeiro', 'BA'), ('Ilhéus', 'BA'), ('Itabuna', 'BA'), ('Lauro de Freitas', 'BA'),
            
            # Distrito Federal
            ('Brasília', 'DF'),
            
            # Goiás
            ('Goiânia', 'GO'), ('Aparecida de Goiânia', 'GO'), ('Anápolis', 'GO'), ('Rio Verde', 'GO'),
            
            # Pernambuco
            ('Recife', 'PE'), ('Jaboatão dos Guararapes', 'PE'), ('Olinda', 'PE'), ('Caruaru', 'PE'),
            ('Petrolina', 'PE'), ('Paulista', 'PE'), ('Cabo de Santo Agostinho', 'PE'),
            
            # Ceará
            ('Fortaleza', 'CE'), ('Caucaia', 'CE'), ('Juazeiro do Norte', 'CE'), ('Maracanaú', 'CE'),
            ('Sobral', 'CE'), ('Crato', 'CE'), ('Itapipoca', 'CE'),
            
            # Pará
            ('Belém', 'PA'), ('Ananindeua', 'PA'), ('Santarém', 'PA'), ('Marabá', 'PA'),
            ('Paragominas', 'PA'), ('Castanhal', 'PA'),
            
            # Santa Catarina
            ('Florianópolis', 'SC'), ('Joinville', 'SC'), ('Blumenau', 'SC'), ('São José', 'SC'),
            ('Chapecó', 'SC'), ('Itajaí', 'SC'), ('Criciúma', 'SC'), ('Palhoça', 'SC'),
            
            # Maranhão
            ('São Luís', 'MA'), ('Imperatriz', 'MA'), ('Caxias', 'MA'), ('Timon', 'MA'),
            
            # Amazonas
            ('Manaus', 'AM'), ('Parintins', 'AM'), ('Itacoatiara', 'AM'), ('Manacapuru', 'AM'),
            
            # Espírito Santo
            ('Vitória', 'ES'), ('Vila Velha', 'ES'), ('Cariacica', 'ES'), ('Serra', 'ES'),
            
            # Paraíba
            ('João Pessoa', 'PB'), ('Campina Grande', 'PB'), ('Santa Rita', 'PB'), ('Patos', 'PB'),
            
            # Rio Grande do Norte
            ('Natal', 'RN'), ('Mossoró', 'RN'), ('Parnamirim', 'RN'), ('São Gonçalo do Amarante', 'RN'),
            
            # Alagoas
            ('Maceió', 'AL'), ('Arapiraca', 'AL'), ('Rio Largo', 'AL'), ('Palmeira dos Índios', 'AL'),
            
            # Mato Grosso
            ('Cuiabá', 'MT'), ('Várzea Grande', 'MT'), ('Rondonópolis', 'MT'), ('Sinop', 'MT'),
            
            # Piauí
            ('Teresina', 'PI'), ('Parnaíba', 'PI'), ('Picos', 'PI'), ('Piripiri', 'PI'),
            
            # Mato Grosso do Sul
            ('Campo Grande', 'MS'), ('Dourados', 'MS'), ('Três Lagoas', 'MS'), ('Corumbá', 'MS'),
            
            # Sergipe
            ('Aracaju', 'SE'), ('Nossa Senhora do Socorro', 'SE'), ('Lagarto', 'SE'), ('Itabaiana', 'SE'),
            
            # Rondônia
            ('Porto Velho', 'RO'), ('Ji-Paraná', 'RO'), ('Ariquemes', 'RO'), ('Vilhena', 'RO'),
            
            # Tocantins
            ('Palmas', 'TO'), ('Araguaína', 'TO'), ('Gurupi', 'TO'), ('Porto Nacional', 'TO'),
            
            # Acre
            ('Rio Branco', 'AC'), ('Cruzeiro do Sul', 'AC'), ('Sena Madureira', 'AC'),
            
            # Amapá
            ('Macapá', 'AP'), ('Santana', 'AP'), ('Laranjal do Jari', 'AP'),
            
            # Roraima
            ('Boa Vista', 'RR'), ('Rorainópolis', 'RR'), ('Caracaraí', 'RR'),
        ]
        
        for city, state in cities:
            display_name = f"{city} - {state}"
            location, created = NormalizedLocation.objects.get_or_create(
                city=city,
                state=state,
                defaults={
                    'display_name': display_name,
                    'is_active': True
                }
            )
            if created:
                self.stdout.write(f'  ✓ Criado: {location.display_name}')
        
        self.stdout.write(self.style.SUCCESS(f'\n✓ População concluída!'))
        self.stdout.write(f'  - Nichos: {NormalizedNiche.objects.filter(is_active=True).count()}')
        self.stdout.write(f'  - Cidades: {NormalizedLocation.objects.filter(is_active=True).count()}')

