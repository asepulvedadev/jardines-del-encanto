export const project = {
  name: "Jardines del Encanto",
  location: "Acacías, Meta",
  phone: "+57 300 834 8478",
  whatsapp: "573008348478",
};
export function whatsappLink(
  message = "Hola, quiero mi cupo para conocer los lotes de Jardines del Encanto. Me interesa el precio de lanzamiento desde $13 millones COP y agendar una visita.",
) {
  return `https://wa.me/${project.whatsapp}?text=${encodeURIComponent(message)}`;
}
export const galleryMedia = [
  {
    type: "video",
    name: "casa-construida",
    title: "Conoce la casa construida",
    alt: "Presentación de una edificación construida en Jardines del Encanto.",
    duration: "0:07",
  },
  {
    type: "image",
    name: "vias-actuales",
    title: "Recorre nuestras vías y lotes",
    alt: "Vista aérea real de las vías internas, los lotes y un kiosco del proyecto.",
  },
  {
    type: "image",
    name: "porteria-actual",
    title: "La entrada a tu nuevo comienzo",
    alt: "Vista aérea real de la portería, el letrero de Jardines del Encanto y la cancha.",
  },
  {
    type: "video",
    name: "parque-infantil",
    title: "Un espacio para jugar",
    alt: "Recorrido real del parque infantil y sus jardines en Jardines del Encanto.",
    duration: "0:08",
  },
] as const;
export const amenityGroups = [
  {
    title: "Compartir",
    text: "Espacios para encontrarse y hacer comunidad.",
    items: ["Salón comunal", "Kiosco social", "Zona BBQ"],
  },
  {
    title: "Moverse",
    text: "Más maneras de disfrutar el tiempo libre.",
    items: [
      "Cancha de fútbol 5 en grama especial",
      "Cancha multifuncional",
      "Cancha de voleibol",
      "Piscina",
    ],
  },
  {
    title: "Respirar",
    text: "Un lugar para bajar el ritmo y estar al aire libre.",
    items: [
      "3 parques infantiles",
      "Sendero",
      "Zona de lectura",
      "Amplias jardinerías",
    ],
  },
] as const;
export const questions = [
  {
    question: "¿Desde cuánto puedo comprar un lote?",
    answer:
      "La oferta informada por el proyecto comienza en $13.000.000 COP para lotes de 7 × 14 m (98 m²). Confirma con un asesor la ubicación del lote, su disponibilidad y las condiciones vigentes antes de tomar una decisión.",
  },
  {
    question: "¿Cómo funciona la financiación?",
    answer:
      "El proyecto ofrece financiación de hasta 24 meses. Solicita al asesor las condiciones completas, incluida la cuota inicial, los intereses si aplican y el calendario de pagos. Esta página no presenta una simulación de crédito.",
  },
  {
    question: "¿Dónde está ubicado el proyecto?",
    answer:
      "Jardines del Encanto está en Acacías, Meta. Escríbenos por WhatsApp para recibir la ubicación exacta, las indicaciones de llegada y coordinar tu visita.",
  },
  {
    question: "¿Qué servicios y vías contempla?",
    answer:
      "La información suministrada contempla agua y energía, y vías embalastradas y vibrocompactadas de 8 metros con sardineles en concreto. Consulta el alcance y las condiciones de entrega de los servicios con el equipo del proyecto.",
  },
  {
    question: "¿Todas las zonas comunes están terminadas?",
    answer:
      "Las fotografías y los videos de la galería muestran el proyecto. El video del inicio es una visualización arquitectónica. El listado describe las zonas informadas por el proyecto, no certifica su estado de entrega. Durante tu visita puedes revisar los avances y confirmar el alcance de cada espacio.",
  },
  {
    question: "¿El plano muestra los lotes disponibles?",
    answer:
      "No. El plano compartido es una referencia de la distribución del proyecto y no refleja disponibilidad en tiempo real. Consulta con un asesor el lote de tu interés, sus medidas y su documentación.",
  },
] as const;
