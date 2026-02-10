# 🎨 UnionPB Elite — Color Specification

Движок UnionPB v3.9 Elite поддерживает полную палитру имен цветов стандарта X11 (библиотека Pillow). Ниже приведена инженерная классификация всех доступных оттенков.

---

## 🔘 Серые и Технические (Grayscale)
`white`, `snow`, `honeydew`, `mintcream`, `azure`, `aliceblue`, `ghostwhite`, `whitesmoke`, `seashell`, `beige`, `oldlace`, `floralwhite`, `ivory`, `antiquewhite`, `linen`, `lavenderblush`, `mistyrose`, `gainsboro`, `lightgray`, `silver`, `darkgray`, `gray`, `dimgray`, `lightslategray`, `slategray`, `darkslategray`, `black`.

## 🔴 Красные и Розовые (Reds & Pinks)
`lightpink`, `pink`, `crimson`, `lavender`, `palevioletred`, `hotpink`, `deeppink`, `mediumvioletred`, `indianred`, `lightcoral`, `salmon`, `darksalmon`, `lightsalmon`, `red`, `firebrick`, `darkred`.

## 🟠 Оранжевые и Коричневые (Oranges & Browns)
`orangered`, `tomato`, `darkorange`, `coral`, `orange`, `lightyellow`, `lemonchiffon`, `lightgoldenrodyellow`, `papayawhip`, `moccasin`, `peachpuff`, `palegoldenrod`, `khaki`, `darkkhaki`, `gold`, `cornsilk`, `wheat`, `burlywood`, `tan`, `rosybrown`, `sandybrown`, `goldenrod`, `darkgoldenrod`, `peru`, `chocolate`, `saddlebrown`, `sienna`, `brown`, `maroon`.

## 🟡 Желтые (Yellows)
`yellow`, `lightyellow`, `lemonchiffon`, `lightgoldenrodyellow`, `papayawhip`, `moccasin`.

## 🟢 Зеленые (Greens)
`lawngreen`, `chartreuse`, `limegreen`, `green`, `forestgreen`, `seagreen`, `mediumseagreen`, `springgreen`, `mediumspringgreen`, `lightgreen`, `palegreen`, `darkseagreen`, `mediumaquamarine`, `yellowgreen`, `olive`, `olivedrab`, `darkolivegreen`, `darkgreen`.

## 🔵 Синие и Голубые (Blues & Cyans)
`lightcyan`, `paleturquoise`, `aquamarine`, `aqua`, `cyan`, `darkturquoise`, `cadetblue`, `mediumturquoise`, `lightsteelblue`, `powderblue`, `lightblue`, `skyblue`, `lightskyblue`, `deepskyblue`, `dodgerblue`, `cornflowerblue`, `steelblue`, `royalblue`, `blue`, `mediumblue`, `darkblue`, `navy`, `midnightblue`.

## 🟣 Фиолетовые (Purples)
`lavender`, `thistle`, `plum`, `violet`, `orchid`, `fuchsia`, `magenta`, `mediumorchid`, `mediumpurple`, `blueviolet`, `darkviolet`, `darkorchid`, `darkmagenta`, `purple`, `indigo`, `slateblue`, `darkslateblue`, `mediumslateblue`.

---

## 💡 Инструкция по применению
Используйте данные имена в командах `/add`, `/line`, `/circle` или `/fill`. 
Пример: `/fill midnightblue 0 0 1023 100`

**Примечание:** Все имена регистронезависимы (движок воспринимает `Gold` и `gold` одинаково).